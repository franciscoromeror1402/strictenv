from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Mapping, Self, TypedDict, cast, get_origin

from msgspec import NODEFAULT, Struct, convert, json

from ._coerce import (
    coerce_value,
    extract_struct_type,
    field_alias,
    field_env_names,
    field_info,
    get_annotations,
    unwrap_annotated,
    validate_constraints,
)
from ._env import build_env_map, format_env_key
from .errors import (
    MissingSettingError,
    NestedStructDepthError,
    ParseSettingError,
    TransformSettingError,
)
from .fields import FieldInfo
from .structs import TransformStruct


class SettingsConfig(TypedDict, total=False):
    env_prefix: str
    case_sensitive: bool
    env_nested_delimiter: str | None
    env_file: str | None
    strict_env_file: bool
    max_nested_struct_depth: int | None


class BaseSettings(TransformStruct):
    """
    Lightweight settings loader inspired by ``pydantic-settings``.

    Supported ``model_config`` keys:
    - ``env_prefix``
    - ``case_sensitive``
    - ``env_nested_delimiter``
    - ``env_file``
    - ``strict_env_file``
    - ``max_nested_struct_depth``
    """

    model_config: ClassVar[SettingsConfig] = {}

    @classmethod
    def write_env_example(cls, path: str) -> None:
        """
        Write an `.env` example file for the settings schema.

        The generated file contains one variable per line with an empty value.
        If a field has `Field(description=...)`, the description is emitted as
        comments immediately above the variable.

        Args:
            path: Output file path for the generated example file.
        """
        config = cls.model_config
        env_prefix = config.get("env_prefix", "")
        case_sensitive = config.get("case_sensitive", False)
        nested_delimiter = config.get("env_nested_delimiter")
        max_nested_struct_depth = cls._get_max_nested_struct_depth()

        entries = cls._collect_env_example_entries(
            struct_type=cls,
            env_prefix=env_prefix,
            nested_delimiter=nested_delimiter,
            case_sensitive=case_sensitive,
            path_parts=(),
            depth=0,
            max_nested_struct_depth=max_nested_struct_depth,
        )

        lines: list[str] = []
        for index, (env_key, description) in enumerate(entries):
            if description:
                for comment_line in description.splitlines():
                    lines.append(f"# {comment_line}")
            lines.append(f"{env_key}=")
            if index != len(entries) - 1:
                lines.append("")

        output = Path(path)
        if output.parent != Path("."):
            output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    @classmethod
    def load(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> Self:
        """
        Build a settings instance from environment values and explicit overrides.

        Args:
            env: Optional environment mapping. If omitted, `os.environ` is used.
            overrides: Optional in-memory values that take precedence over env data.

        Returns:
            A fully parsed instance of the settings class.

        Raises:
            MissingSettingError: If a required field has no value and no default.
            ParseSettingError: If a raw value cannot be coerced to the target type.
            EnvFileNotFoundError: If `env_file` is configured and missing in strict mode.
            EnvFileReadError: If `env_file` exists but cannot be read in strict mode.
            EnvFileFormatError: If `env_file` contains invalid lines in strict mode.
            EnvKeyConflictError: If case-insensitive env keys collide in strict mode.
            NestedStructDepthError: If nested struct traversal exceeds the depth limit.
        """
        config = cls.model_config
        env_prefix = config.get("env_prefix", "")
        case_sensitive = config.get("case_sensitive", False)
        env_file = config.get("env_file")
        strict_env_file = config.get("strict_env_file", True)
        nested_delimiter = config.get("env_nested_delimiter")
        max_nested_struct_depth = cls._get_max_nested_struct_depth()

        env_map = build_env_map(
            env,
            env_file,
            case_sensitive,
            strict_env_file=strict_env_file,
        )
        data: dict[str, Any] = {}

        if nested_delimiter:
            cls._apply_nested_env(
                env_map=env_map,
                data=data,
                struct_type=cls,
                env_prefix=env_prefix,
                nested_delimiter=nested_delimiter,
                case_sensitive=case_sensitive,
                max_nested_struct_depth=max_nested_struct_depth,
            )

        if overrides:
            data.update(overrides)

        annotations = cls._get_declared_fields(cls)
        for field_name, field_type in annotations.items():
            if field_name in data:
                continue

            has_default, raw_default = cls._get_struct_default(cls, field_name)

            found_value = False
            for env_name in field_env_names(
                field_name,
                field_type,
                default=raw_default if has_default else None,
            ):
                env_key = format_env_key(env_prefix, env_name, case_sensitive)
                if env_key not in env_map:
                    continue
                raw = env_map[env_key]
                data[field_name] = raw
                found_value = True
                break
            if found_value:
                continue

            if has_default and isinstance(raw_default, FieldInfo):
                if not raw_default.is_required():
                    data[field_name] = raw_default.default
                    continue

            if not cls._field_has_default(cls, field_name):
                first_env_name = field_env_names(
                    field_name,
                    field_type,
                    default=raw_default if has_default else None,
                )[0]
                env_key = format_env_key(env_prefix, first_env_name, case_sensitive)
                raise MissingSettingError(field_name=field_name, env_key=env_key)

        cls._coerce_nested_structs(
            data,
            cls,
            max_nested_struct_depth=max_nested_struct_depth,
        )
        loaded = convert(data, type=cls)
        return cls._apply_struct_transforms(loaded, field_path="")

    @classmethod
    def _get_declared_fields(cls, struct_type: type[Struct]) -> dict[str, Any]:
        """
        Return runtime field annotations for a `Struct`, excluding config/class vars.

        Args:
            struct_type: Struct type to introspect.

        Returns:
            A mapping of field names to annotated types.
        """
        annotations = get_annotations(struct_type)
        declared: dict[str, Any] = {}
        for field_name, field_type in annotations.items():
            if field_name == "model_config":
                continue
            if get_origin(field_type) is ClassVar:
                continue
            declared[field_name] = field_type
        return declared

    @classmethod
    def _collect_env_example_entries(
        cls,
        *,
        struct_type: type[Struct],
        env_prefix: str,
        nested_delimiter: str | None,
        case_sensitive: bool,
        path_parts: tuple[str, ...],
        depth: int,
        max_nested_struct_depth: int | None,
    ) -> list[tuple[str, str | None]]:
        entries: list[tuple[str, str | None]] = []
        annotations = cls._get_declared_fields(struct_type)

        for field_name, field_type in annotations.items():
            has_default, raw_default = cls._get_struct_default(struct_type, field_name)
            default_value = raw_default if has_default else None

            info = field_info(field_type, default=default_value)
            env_name = field_env_names(
                field_name,
                field_type,
                default=default_value,
            )[0]
            nested_struct = extract_struct_type(field_type)

            if nested_struct is not None and nested_delimiter:
                next_depth = depth + 1
                next_path_parts = (*path_parts, env_name)
                cls._ensure_nested_depth(
                    max_nested_struct_depth=max_nested_struct_depth,
                    depth=next_depth,
                    field_path=".".join(next_path_parts),
                )
                entries.extend(
                    cls._collect_env_example_entries(
                        struct_type=nested_struct,
                        env_prefix=env_prefix,
                        nested_delimiter=nested_delimiter,
                        case_sensitive=case_sensitive,
                        path_parts=next_path_parts,
                        depth=next_depth,
                        max_nested_struct_depth=max_nested_struct_depth,
                    )
                )
                continue

            if path_parts and nested_delimiter:
                env_path = nested_delimiter.join((*path_parts, env_name))
            else:
                env_path = env_name

            env_key = format_env_key(env_prefix, env_path, case_sensitive)
            description = info.description if info is not None else None
            entries.append((env_key, description))

        return entries

    @classmethod
    def _get_max_nested_struct_depth(cls) -> int | None:
        config_value = cls.model_config.get("max_nested_struct_depth")
        if config_value is None:
            return None
        if not isinstance(config_value, int) or config_value <= 0:
            raise ValueError("model_config['max_nested_struct_depth'] must be a positive integer")
        return config_value

    @staticmethod
    def _ensure_nested_depth(
        *,
        max_nested_struct_depth: int | None,
        depth: int,
        field_path: str,
    ) -> None:
        if max_nested_struct_depth is None:
            return
        if depth <= max_nested_struct_depth:
            return
        raise NestedStructDepthError(
            field_path=field_path,
            depth=depth,
            max_depth=max_nested_struct_depth,
        )

    @staticmethod
    def _get_struct_default(struct_type: type[Struct], field_name: str) -> tuple[bool, Any]:
        """
        Return whether a struct field has a declared default and the default value.

        Args:
            struct_type: Struct type that defines the field.
            field_name: Name of the field to check.

        Returns:
            A tuple `(has_default, default_value)`.
        """
        fields = struct_type.__struct_fields__
        defaults = struct_type.__struct_defaults__
        default_start = len(fields) - len(defaults)
        try:
            field_index = fields.index(field_name)
        except ValueError:
            return False, None
        if field_index < default_start:
            return False, None
        default_index = field_index - default_start
        default_value = defaults[default_index]
        if default_value is NODEFAULT:
            return False, None
        return True, default_value

    @classmethod
    def _field_has_default(cls, struct_type: type[Struct], field_name: str) -> bool:
        """
        Check whether a struct field is optional because it has a default value.

        Args:
            struct_type: Struct type that defines the field.
            field_name: Name of the field to check.

        Returns:
            `True` when the field has a default, otherwise `False`.
        """
        has_default, default_value = cls._get_struct_default(struct_type, field_name)
        if not has_default:
            return False
        if isinstance(default_value, FieldInfo):
            return not default_value.is_required()
        return True

    @staticmethod
    def _decode_nested_struct_payload(
        *,
        raw_payload: str,
        field_path: str,
        target_type: Any,
    ) -> dict[str, Any]:
        try:
            decoded = json.decode(raw_payload.encode("utf-8"))
        except Exception as exc:
            raise ParseSettingError(
                field_name=field_path,
                target_type=target_type,
                raw_value=raw_payload,
            ) from exc
        if not isinstance(decoded, dict):
            raise ParseSettingError(
                field_name=field_path,
                target_type=target_type,
                raw_value=raw_payload,
            )
        return decoded

    @classmethod
    def _coerce_field_value(
        cls,
        *,
        struct_type: type[Struct],
        field_name: str,
        field_type: Any,
        raw_value: Any,
        info: FieldInfo | None,
        field_path: str,
        depth: int,
        max_nested_struct_depth: int | None,
    ) -> Any:
        transform_owner: type[TransformStruct] | None = None
        if isinstance(struct_type, type) and issubclass(struct_type, TransformStruct):
            transform_owner = struct_type

        value: Any = raw_value
        nested_struct = extract_struct_type(field_type)

        if isinstance(value, str):
            if transform_owner is not None:
                value = transform_owner._apply_before_transforms(
                    field_name=field_name,
                    value=value,
                    target_type=field_type,
                    field_path=field_path,
                )

            if isinstance(value, str):
                if nested_struct is not None:
                    decoded_payload = cls._decode_nested_struct_payload(
                        raw_payload=value,
                        field_path=field_path,
                        target_type=field_type,
                    )
                    next_depth = depth + 1
                    cls._ensure_nested_depth(
                        max_nested_struct_depth=max_nested_struct_depth,
                        depth=next_depth,
                        field_path=field_path,
                    )
                    value = cls._coerce_struct_data(
                        raw=decoded_payload,
                        struct_type=nested_struct,
                        field_path=field_path,
                        depth=next_depth,
                        max_nested_struct_depth=max_nested_struct_depth,
                    )
                else:
                    value = coerce_value(
                        value,
                        field_type,
                        field_name=field_path,
                        field=info,
                    )
            else:
                if (
                    transform_owner is not None
                    and not transform_owner._is_value_compatible_with_annotation(value, field_type)
                ):
                    raise TransformSettingError(
                        field_name=field_path,
                        mode="before",
                        transform_name="<before-transform-chain>",
                        target_type=field_type,
                        value_repr=repr(value),
                        reason="before transform returned incompatible type",
                    )

        elif isinstance(value, dict) and nested_struct is not None:
            next_depth = depth + 1
            cls._ensure_nested_depth(
                max_nested_struct_depth=max_nested_struct_depth,
                depth=next_depth,
                field_path=field_path,
            )
            value = cls._coerce_struct_data(
                raw=value,
                struct_type=nested_struct,
                field_path=field_path,
                depth=next_depth,
                max_nested_struct_depth=max_nested_struct_depth,
            )

        if transform_owner is not None:
            value = transform_owner._apply_after_transforms(
                field_name=field_name,
                value=value,
                target_type=field_type,
                field_path=field_path,
            )

        return validate_constraints(
            value,
            unwrap_annotated(field_type),
            field_name=field_path,
            field=info,
            raw_value=repr(raw_value),
        )

    @classmethod
    def _match_struct_field(
        cls,
        env_name: str,
        struct_type: type[Struct],
        *,
        case_sensitive: bool,
    ) -> str | None:
        """
        Resolve an env segment to a struct field name, including alias lookup.

        Args:
            env_name: Raw env key segment to resolve.
            struct_type: Struct type whose fields will be matched.
            case_sensitive: Whether matching should preserve case.

        Returns:
            The matched field name, or `None` when no match is found.
        """
        annotations = cls._get_declared_fields(struct_type)

        if case_sensitive:
            if env_name in annotations:
                return env_name
        else:
            env_lower = env_name.lower()
            for field_name in annotations:
                if field_name.lower() == env_lower:
                    return field_name

        for field_name, annotation in annotations.items():
            has_default, raw_default = cls._get_struct_default(struct_type, field_name)
            alias = field_alias(
                annotation,
                default=raw_default if has_default else None,
            )
            if alias is None:
                continue
            if case_sensitive and alias == env_name:
                return field_name
            if not case_sensitive and alias.lower() == env_name.lower():
                return field_name

        return None

    @classmethod
    def _apply_nested_env(
        cls,
        *,
        env_map: Mapping[str, str],
        data: dict[str, Any],
        struct_type: type[Struct],
        env_prefix: str,
        nested_delimiter: str,
        case_sensitive: bool,
        max_nested_struct_depth: int | None,
    ) -> None:
        """
        Project flat env keys into nested dictionaries for nested `Struct` fields.

        Args:
            env_map: Normalized environment key/value mapping.
            data: Mutable output payload to update.
            struct_type: Root settings struct type.
            env_prefix: Prefix configured for this settings class.
            nested_delimiter: Delimiter used to represent nested paths.
            case_sensitive: Whether key matching should be case-sensitive.
        """
        prefix = env_prefix if case_sensitive else env_prefix.upper()
        for key, value in env_map.items():
            if prefix and not key.startswith(prefix):
                continue
            stripped = key[len(prefix) :] if prefix else key
            if nested_delimiter not in stripped:
                continue
            parts = [part for part in stripped.split(nested_delimiter) if part]
            if len(parts) < 2:
                continue
            cls._set_nested(
                data=data,
                struct_type=struct_type,
                parts=parts,
                value=value,
                case_sensitive=case_sensitive,
                max_nested_struct_depth=max_nested_struct_depth,
            )

    @classmethod
    def _set_nested(
        cls,
        *,
        data: dict[str, Any],
        struct_type: type[Struct],
        parts: list[str],
        value: str,
        case_sensitive: bool,
        max_nested_struct_depth: int | None,
    ) -> None:
        """
        Insert a nested env value into `data` using struct-aware field matching.

        Args:
            data: Mutable payload receiving parsed values.
            struct_type: Struct type representing the current nesting level.
            parts: Split env path segments.
            value: Raw string value from the environment.
            case_sensitive: Whether field matching should be case-sensitive.
        """
        current: dict[str, Any] = data
        current_struct: type[Struct] = struct_type
        field_path_parts: list[str] = []

        for index, part in enumerate(parts):
            matched_field = cls._match_struct_field(
                part,
                current_struct,
                case_sensitive=case_sensitive,
            )
            if matched_field is None:
                return

            field_path_parts.append(matched_field)
            if index == len(parts) - 1:
                current[matched_field] = value
                return

            current_annotations = cls._get_declared_fields(current_struct)
            next_type = extract_struct_type(current_annotations[matched_field])
            if next_type is None:
                return
            cls._ensure_nested_depth(
                max_nested_struct_depth=max_nested_struct_depth,
                depth=len(field_path_parts),
                field_path=".".join(field_path_parts),
            )

            next_value = current.get(matched_field)
            if not isinstance(next_value, dict):
                next_value = {}
                current[matched_field] = next_value
            current = next_value
            current_struct = next_type

    @classmethod
    def _coerce_nested_structs(
        cls,
        data: dict[str, Any],
        struct_type: type[Struct],
        *,
        max_nested_struct_depth: int | None,
    ) -> None:
        """
        Coerce nested dictionaries and raw strings into declared field types.

        Args:
            data: Mutable payload with raw values.
            struct_type: Struct type used as coercion schema.
        """
        annotations = cls._get_declared_fields(struct_type)
        for field_name, field_type in annotations.items():
            if field_name not in data:
                continue
            has_default, raw_default = cls._get_struct_default(struct_type, field_name)
            info = field_info(field_type, default=raw_default if has_default else None)
            data[field_name] = cls._coerce_field_value(
                struct_type=struct_type,
                field_name=field_name,
                field_type=field_type,
                raw_value=data[field_name],
                info=info,
                field_path=field_name,
                depth=0,
                max_nested_struct_depth=max_nested_struct_depth,
            )

    @classmethod
    def _coerce_struct_data(
        cls,
        *,
        raw: dict[str, Any],
        struct_type: type[Struct],
        field_path: str,
        depth: int,
        max_nested_struct_depth: int | None,
    ) -> Any:
        """
        Recursively coerce a nested dictionary into a concrete struct instance.

        Args:
            raw: Raw nested dictionary values.
            struct_type: Target nested struct type.
            field_path: Dot path used to report parsing errors.

        Returns:
            A parsed struct instance of `struct_type`.

        Raises:
            ParseSettingError: If conversion to the struct type fails.
        """
        annotations = cls._get_declared_fields(struct_type)
        parsed: dict[str, Any] = {}

        for field_name, field_type in annotations.items():
            has_default, raw_default = cls._get_struct_default(struct_type, field_name)
            info = field_info(field_type, default=raw_default if has_default else None)
            nested_path = f"{field_path}.{field_name}"

            if field_name not in raw:
                if (
                    has_default
                    and isinstance(raw_default, FieldInfo)
                    and not raw_default.is_required()
                ):
                    parsed[field_name] = cls._coerce_field_value(
                        struct_type=struct_type,
                        field_name=field_name,
                        field_type=field_type,
                        raw_value=raw_default.default,
                        info=info,
                        field_path=nested_path,
                        depth=depth,
                        max_nested_struct_depth=max_nested_struct_depth,
                    )
                continue
            parsed[field_name] = cls._coerce_field_value(
                struct_type=struct_type,
                field_name=field_name,
                field_type=field_type,
                raw_value=raw[field_name],
                info=info,
                field_path=nested_path,
                depth=depth,
                max_nested_struct_depth=max_nested_struct_depth,
            )

        try:
            converted = convert(parsed, type=struct_type)
        except Exception as exc:
            raise ParseSettingError(
                field_name=field_path,
                target_type=struct_type,
                raw_value=repr(raw),
            ) from exc
        if isinstance(struct_type, type) and issubclass(struct_type, TransformStruct):
            converted = struct_type._apply_struct_transforms(
                cast(TransformStruct, converted),
                field_path=field_path,
            )
        return converted
