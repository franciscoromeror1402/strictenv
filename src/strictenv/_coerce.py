from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Mapping as MappingABC
from collections.abc import MutableMapping as MutableMappingABC
from collections.abc import Sequence as SequenceABC
from collections.abc import Set as SetABC
from datetime import date, datetime, time, timedelta
from enum import Enum
from re import fullmatch
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints

from msgspec import NODEFAULT, Meta, Struct, json

from .errors import ParseSettingError
from .fields import FieldInfo


def iter_annotated_metadata(annotation: Any) -> tuple[Any, list[Any]]:
    """
    Unwrap nested `typing.Annotated` hints and collect all metadata entries.

    Args:
        annotation: Type annotation that may include `Annotated` wrappers.

    Returns:
        A tuple with the unwrapped base annotation and collected metadata list.
    """
    metadata: list[Any] = []
    current = annotation
    while get_origin(current) is Annotated:
        args = get_args(current)
        current = args[0]
        metadata.extend(args[1:])
    return current, metadata


def unwrap_annotated(annotation: Any) -> Any:
    """
    Return the base type annotation without `Annotated` metadata.

    Args:
        annotation: Type annotation that may include metadata.

    Returns:
        The underlying type annotation.
    """
    base_annotation, _ = iter_annotated_metadata(annotation)
    return base_annotation


def get_annotations(struct_type: type[Any]) -> dict[str, Any]:
    """
    Read annotations from a struct type, preserving extras when possible.

    Args:
        struct_type: Class or struct to inspect.

    Returns:
        Mapping of field names to annotations.
    """
    try:
        annotations = get_type_hints(struct_type, include_extras=True)
    except TypeError:
        annotations = get_type_hints(struct_type)
    except Exception:
        annotations = dict(getattr(struct_type, "__annotations__", {}))

    return _inject_field_descriptions_into_meta(struct_type, annotations)


_META_ATTRS = (
    "gt",
    "ge",
    "lt",
    "le",
    "multiple_of",
    "pattern",
    "min_length",
    "max_length",
    "tz",
    "title",
    "description",
    "examples",
    "extra_json_schema",
    "extra",
)


def _get_struct_defaults_map(struct_type: type[Any]) -> dict[str, Any]:
    fields = getattr(struct_type, "__struct_fields__", ())
    defaults = getattr(struct_type, "__struct_defaults__", ())
    if not fields:
        return {}

    default_start = len(fields) - len(defaults)
    by_name: dict[str, Any] = {}
    for field_index, field_name in enumerate(fields):
        if field_index < default_start:
            continue
        default_value = defaults[field_index - default_start]
        if default_value is NODEFAULT:
            continue
        by_name[field_name] = default_value
    return by_name


def _extract_attribute_doc_descriptions(struct_type: type[Any]) -> dict[str, str]:
    try:
        source = inspect.getsource(struct_type)
    except (OSError, TypeError):
        return {}

    try:
        module = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return {}

    class_nodes = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef) and node.name == struct_type.__name__
    ]
    if not class_nodes:
        return {}

    class_node = min(class_nodes, key=lambda node: node.lineno)
    descriptions: dict[str, str] = {}
    body = class_node.body

    for index, node in enumerate(body):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if index + 1 >= len(body):
            continue

        next_node = body[index + 1]
        if not isinstance(next_node, ast.Expr):
            continue
        if not isinstance(next_node.value, ast.Constant):
            continue
        if not isinstance(next_node.value.value, str):
            continue

        literal = next_node.value.value.strip()
        if literal:
            descriptions[node.target.id] = literal

    return descriptions


def _annotation_meta_description(annotation: Any) -> str | None:
    _, metadata = iter_annotated_metadata(annotation)
    for meta in metadata:
        if isinstance(meta, Meta) and meta.description:
            return meta.description
    return None


def _meta_with_description(meta: Meta, description: str) -> Meta:
    kwargs = {name: getattr(meta, name) for name in _META_ATTRS}
    kwargs["description"] = description
    return Meta(**kwargs)


def _annotation_with_meta_description(annotation: Any, description: str) -> Any:
    base, metadata = iter_annotated_metadata(annotation)
    first_meta_index: int | None = None

    for idx, meta in enumerate(metadata):
        if isinstance(meta, Meta):
            first_meta_index = idx
            break

    if first_meta_index is None:
        return Annotated[base, *metadata, Meta(description=description)]

    current_meta = metadata[first_meta_index]
    assert isinstance(current_meta, Meta)
    if current_meta.description == description:
        return annotation

    metadata[first_meta_index] = _meta_with_description(current_meta, description)
    return Annotated[base, *metadata]


def _inject_field_descriptions_into_meta(
    struct_type: type[Any],
    annotations: dict[str, Any],
) -> dict[str, Any]:
    defaults = _get_struct_defaults_map(struct_type)
    doc_descriptions = _extract_attribute_doc_descriptions(struct_type)
    updated = dict(annotations)
    changed = False

    for field_name, annotation in annotations.items():
        default = defaults.get(field_name)
        info = field_info(annotation, default=default)
        field_description = info.description if info is not None else None
        existing_meta_description = _annotation_meta_description(annotation)
        doc_description = doc_descriptions.get(field_name)

        description = field_description or existing_meta_description or doc_description
        if description is None:
            continue

        new_annotation = _annotation_with_meta_description(annotation, description)
        if new_annotation is annotation:
            continue
        updated[field_name] = new_annotation
        changed = True

    if changed:
        current_annotations = getattr(struct_type, "__annotations__", None)
        if isinstance(current_annotations, dict):
            current_annotations.update(updated)

    return updated


def _field_from_annotation(annotation: Any) -> FieldInfo | None:
    _, metadata = iter_annotated_metadata(annotation)
    for meta in metadata:
        if isinstance(meta, FieldInfo):
            return meta
    return None


def _merge_field_info(base: FieldInfo | None, override: FieldInfo | None) -> FieldInfo | None:
    if base is None:
        return override
    if override is None:
        return base
    return FieldInfo(
        override.default,
        alias=override.alias if override.alias is not None else base.alias,
        description=(
            override.description
            if override.description is not None
            else base.description
        ),
        gt=override.gt if override.gt is not None else base.gt,
        ge=override.ge if override.ge is not None else base.ge,
        lt=override.lt if override.lt is not None else base.lt,
        le=override.le if override.le is not None else base.le,
        min_length=(
            override.min_length
            if override.min_length is not None
            else base.min_length
        ),
        max_length=(
            override.max_length
            if override.max_length is not None
            else base.max_length
        ),
    )


def field_info(annotation: Any, *, default: Any = None) -> FieldInfo | None:
    """
    Resolve effective `Field` metadata from annotation metadata and default value.

    Args:
        annotation: Field annotation that may include `Annotated[..., Field(...)]`.
        default: Field default value from class definition (if any).

    Returns:
        The effective field metadata, or `None` when no metadata exists.
    """
    annotated = _field_from_annotation(annotation)
    from_default = default if isinstance(default, FieldInfo) else None
    return _merge_field_info(annotated, from_default)


def field_alias(annotation: Any, *, default: Any = None) -> str | None:
    """
    Extract the effective alias configured through `Field`.

    Args:
        annotation: Field annotation that may include `Field` metadata.
        default: Optional class-level default value.

    Returns:
        Alias string when configured, otherwise `None`.
    """
    info = field_info(annotation, default=default)
    if info is None:
        return None
    return info.alias


def field_env_names(field_name: str, annotation: Any, *, default: Any = None) -> tuple[str, ...]:
    """
    Return preferred environment variable names for a field.

    Args:
        field_name: Declared field name.
        annotation: Field annotation with optional alias metadata.
        default: Optional class-level default value.

    Returns:
        Tuple of candidate env names, with alias first when present.
    """
    alias = field_alias(annotation, default=default)
    if alias is None or alias == field_name:
        return (field_name,)
    return (alias, field_name)


def parse_bool(raw: str) -> bool:
    """
    Parse a human-friendly boolean string.

    Args:
        raw: Raw string value from environment input.

    Returns:
        Parsed boolean value.

    Raises:
        ValueError: If the input is not a recognized boolean token.
    """
    value = raw.strip().lower()
    if value in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw}")


def parse_datetime(raw: str) -> datetime:
    """
    Parse an ISO8601 datetime value from environment input.

    Args:
        raw: Raw string value from environment input.

    Returns:
        Parsed timezone-aware or naive datetime.
    """
    value = raw.strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value)


def parse_date(raw: str) -> date:
    """
    Parse an ISO8601 date value (`YYYY-MM-DD`).

    Args:
        raw: Raw string value from environment input.

    Returns:
        Parsed date.
    """
    return date.fromisoformat(raw.strip())


def parse_time(raw: str) -> time:
    """
    Parse an ISO8601 time value.

    Args:
        raw: Raw string value from environment input.

    Returns:
        Parsed time.
    """
    value = raw.strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return time.fromisoformat(value)


def parse_timedelta(raw: str) -> timedelta:
    """
    Parse a duration from one of the supported textual formats.

    Supported formats:
    - ISO8601 duration (e.g. `PT1H30M`)
    - `HH:MM[:SS[.ffffff]]` clock-like duration
    - Numeric seconds (int/float), e.g. `90` or `0.5`

    Args:
        raw: Raw string value from environment input.

    Returns:
        Parsed timedelta.
    """
    value = raw.strip()
    if not value:
        raise ValueError("Empty duration value")

    if fullmatch(r"[+-]?\d+(\.\d+)?", value):
        return timedelta(seconds=float(value))

    if ":" in value:
        return _parse_clock_timedelta(value)

    return json.decode(json.encode(value), type=timedelta)


def _parse_clock_timedelta(value: str) -> timedelta:
    sign = 1
    working = value
    if working.startswith("-"):
        sign = -1
        working = working[1:]
    elif working.startswith("+"):
        working = working[1:]

    parts = working.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"Invalid clock duration format: {value}")

    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2]) if len(parts) == 3 else 0.0

    if not 0 <= minutes < 60:
        raise ValueError(f"Invalid minutes value in duration: {value}")
    if not 0 <= seconds < 60:
        raise ValueError(f"Invalid seconds value in duration: {value}")

    total_seconds = sign * ((hours * 3600) + (minutes * 60) + seconds)
    return timedelta(seconds=total_seconds)


def validate_constraints(
    value: Any,
    target_type: Any,
    *,
    field_name: str,
    field: FieldInfo | None = None,
    raw_value: str | None = None,
) -> Any:
    """
    Validate parsed values against numeric and length constraints from `Field`.

    Args:
        value: Parsed value to validate.
        target_type: Declared target type for error reporting.
        field_name: Field path used for error reporting.
        field: Effective field metadata containing constraints.
        raw_value: Raw value representation used in parse errors.

    Returns:
        The validated value.

    Raises:
        ParseSettingError: If any constraint fails.
    """
    if field is None or value is None:
        return value

    try:
        if field.gt is not None and not value > field.gt:
            raise ValueError(f"Value must be > {field.gt!r}")
        if field.ge is not None and not value >= field.ge:
            raise ValueError(f"Value must be >= {field.ge!r}")
        if field.lt is not None and not value < field.lt:
            raise ValueError(f"Value must be < {field.lt!r}")
        if field.le is not None and not value <= field.le:
            raise ValueError(f"Value must be <= {field.le!r}")

        if field.min_length is not None and len(value) < field.min_length:
            raise ValueError(f"Length must be >= {field.min_length}")
        if field.max_length is not None and len(value) > field.max_length:
            raise ValueError(f"Length must be <= {field.max_length}")
    except ParseSettingError:
        raise
    except Exception as exc:
        raise ParseSettingError(
            field_name=field_name,
            target_type=target_type,
            raw_value=raw_value if raw_value is not None else repr(value),
        ) from exc

    return value


def extract_struct_type(field_type: Any) -> type[Struct] | None:
    """
    Extract a `msgspec.Struct` subtype from direct or union field annotations.

    Args:
        field_type: Field annotation to inspect.

    Returns:
        Struct subtype when found, otherwise `None`.
    """
    candidate = unwrap_annotated(field_type)
    if isinstance(candidate, type) and issubclass(candidate, Struct):
        return candidate

    origin = get_origin(candidate)
    if origin in {Union, UnionType}:
        for arg in get_args(candidate):
            if arg is type(None):
                continue
            if isinstance(arg, type) and issubclass(arg, Struct):
                return arg

    return None


def is_struct_type(field_type: Any) -> bool:
    """
    Check if an annotation represents (or includes) a `Struct` type.

    Args:
        field_type: Annotation to evaluate.

    Returns:
        `True` when a struct type can be extracted, otherwise `False`.
    """
    return extract_struct_type(field_type) is not None


def coerce_value(
    raw: str,
    target_type: Any,
    *,
    field_name: str,
    field: FieldInfo | None = None,
) -> Any:
    """
    Convert a raw environment string into the declared target type.

    Args:
        raw: Raw string value to parse.
        target_type: Declared type annotation for the field.
        field_name: Field path used for error reporting.
        field: Additional field metadata and validations.

    Returns:
        Parsed value in the target type.

    Raises:
        ParseSettingError: If parsing fails for all supported conversion paths.
    """
    effective_field = _merge_field_info(_field_from_annotation(target_type), field)
    target_type = unwrap_annotated(target_type)
    origin = get_origin(target_type)
    args = get_args(target_type)

    try:
        parsed: Any
        if target_type is Any:
            parsed = raw
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )

        if origin is None and target_type is str:
            parsed = raw
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )
        if origin is None and target_type is bool:
            parsed = parse_bool(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )
        if origin is None and target_type is int:
            parsed = int(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )
        if origin is None and target_type is float:
            parsed = float(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )
        if origin is None and target_type is datetime:
            parsed = parse_datetime(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )
        if origin is None and target_type is date:
            parsed = parse_date(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )
        if origin is None and target_type is time:
            parsed = parse_time(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )
        if origin is None and target_type is timedelta:
            parsed = parse_timedelta(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )

        if (
            origin is None
            and isinstance(target_type, type)
            and issubclass(target_type, Enum)
        ):
            try:
                parsed = target_type[raw]
            except KeyError:
                parsed = target_type(raw)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )

        if (
            origin is None
            and isinstance(target_type, type)
            and issubclass(target_type, Struct)
        ):
            parsed = json.decode(raw.encode("utf-8"), type=target_type)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )

        if origin in {
            list,
            dict,
            tuple,
            set,
            frozenset,
            MappingABC,
            MutableMappingABC,
            SequenceABC,
            SetABC,
        }:
            parsed = json.decode(raw.encode("utf-8"), type=target_type)
            return validate_constraints(
                parsed,
                target_type,
                field_name=field_name,
                field=effective_field,
                raw_value=raw,
            )

        if origin in {Union, UnionType}:
            last_error: ParseSettingError | None = None
            for arg in args:
                if arg is type(None):
                    continue
                try:
                    return coerce_value(
                        raw,
                        arg,
                        field_name=field_name,
                        field=effective_field,
                    )
                except ParseSettingError as exc:
                    last_error = exc
            if last_error is not None:
                raise ParseSettingError(
                    field_name=field_name,
                    target_type=target_type,
                    raw_value=raw,
                ) from last_error
            if type(None) in args:
                raise ParseSettingError(
                    field_name=field_name,
                    target_type=target_type,
                    raw_value=raw,
                )

        parsed = json.decode(raw.encode("utf-8"), type=target_type)
        return validate_constraints(
            parsed,
            target_type,
            field_name=field_name,
            field=effective_field,
            raw_value=raw,
        )
    except ParseSettingError:
        raise
    except Exception as exc:
        raise ParseSettingError(
            field_name=field_name,
            target_type=target_type,
            raw_value=raw,
        ) from exc
