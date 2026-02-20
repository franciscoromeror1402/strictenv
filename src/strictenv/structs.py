from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import UnionType
from typing import Any, ClassVar, Union, get_args, get_origin, get_type_hints

from msgspec import Struct

from ._coerce import unwrap_annotated
from .errors import TransformSettingError
from .transforms import TransformMode, get_transform_meta


@dataclass(frozen=True)
class _RegisteredTransform:
    field_name: str
    mode: TransformMode
    transform_name: str
    func: Any
    takes_cls: bool
    order: int


TransformRegistry = dict[str, dict[TransformMode, list[_RegisteredTransform]]]


class TransformStruct(Struct):
    """
    `msgspec.Struct` subclass with field transforms.

    Transforms are declared with `@transform("field", mode="before" | "after")`.
    """

    __field_transforms__: ClassVar[TransformRegistry] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        registry = cls._clone_inherited_transform_registry()
        declared = cls._collect_declared_transforms()

        for transform_entry in declared:
            cls._remove_transform_name(registry, transform_entry.transform_name)
            field_transforms = registry.setdefault(
                transform_entry.field_name,
                {"before": [], "after": []},
            )
            field_transforms[transform_entry.mode].append(transform_entry)

        cls.__field_transforms__ = registry

    @classmethod
    def _clone_inherited_transform_registry(cls) -> TransformRegistry:
        cloned: TransformRegistry = {}
        for base in reversed(cls.__mro__[1:]):
            base_registry = getattr(base, "__field_transforms__", None)
            if not base_registry:
                continue
            for field_name, modes in base_registry.items():
                target = cloned.setdefault(field_name, {"before": [], "after": []})
                target["before"].extend(modes.get("before", []))
                target["after"].extend(modes.get("after", []))
        return cloned

    @classmethod
    def _collect_declared_transforms(cls) -> list[_RegisteredTransform]:
        available_fields = cls._get_available_transform_fields()
        declared: list[_RegisteredTransform] = []

        for attr_name, attr_value in cls.__dict__.items():
            meta = get_transform_meta(attr_value)
            if meta is None:
                continue
            if meta.field_name not in available_fields:
                raise TransformSettingError(
                    field_name=meta.field_name,
                    mode=meta.mode,
                    transform_name=attr_name,
                    target_type=Any,
                    value_repr=repr(attr_value),
                    reason="transform field is not declared in class",
                )

            if isinstance(attr_value, (classmethod, staticmethod)):
                func = attr_value.__func__
            else:
                func = attr_value
            takes_cls = cls._resolve_transform_signature(func, meta=meta, attr_name=attr_name)
            declared.append(
                _RegisteredTransform(
                    field_name=meta.field_name,
                    mode=meta.mode,
                    transform_name=attr_name,
                    func=func,
                    takes_cls=takes_cls,
                    order=meta.order,
                )
            )

        declared.sort(key=lambda item: item.order)
        return declared

    @classmethod
    def _get_available_transform_fields(cls) -> set[str]:
        try:
            hints = get_type_hints(cls, include_extras=True)
        except TypeError:
            hints = get_type_hints(cls)
        except Exception:
            hints = dict(getattr(cls, "__annotations__", {}))

        available: set[str] = set()
        for field_name, field_type in hints.items():
            if field_name == "model_config":
                continue
            if get_origin(field_type) is ClassVar:
                continue
            available.add(field_name)
        return available

    @classmethod
    def _resolve_transform_signature(
        cls,
        func: Any,
        *,
        meta: Any,
        attr_name: str,
    ) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError) as exc:
            raise TransformSettingError(
                field_name=meta.field_name,
                mode=meta.mode,
                transform_name=attr_name,
                target_type=Any,
                value_repr=repr(func),
                reason=f"invalid transform signature: {exc}",
            ) from exc

        positional_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(positional_params) == 1:
            return False
        if len(positional_params) == 2:
            return True
        raise TransformSettingError(
            field_name=meta.field_name,
            mode=meta.mode,
            transform_name=attr_name,
            target_type=Any,
            value_repr=repr(func),
            reason="transform must accept (value) or (cls, value)",
        )

    @staticmethod
    def _remove_transform_name(registry: TransformRegistry, transform_name: str) -> None:
        for field_modes in registry.values():
            field_modes["before"] = [
                item for item in field_modes["before"] if item.transform_name != transform_name
            ]
            field_modes["after"] = [
                item for item in field_modes["after"] if item.transform_name != transform_name
            ]

    @classmethod
    def _get_field_transforms(
        cls,
        field_name: str,
        mode: TransformMode,
    ) -> list[_RegisteredTransform]:
        by_field = cls.__field_transforms__.get(field_name)
        if by_field is None:
            return []
        return by_field.get(mode, [])

    @classmethod
    def _apply_before_transforms(
        cls,
        *,
        field_name: str,
        value: str,
        target_type: Any,
        field_path: str,
    ) -> Any:
        current: Any = value
        for transform_entry in cls._get_field_transforms(field_name, "before"):
            current = cls._invoke_transform(
                transform_entry,
                value=current,
                target_type=target_type,
                field_path=field_path,
            )
        return current

    @classmethod
    def _apply_after_transforms(
        cls,
        *,
        field_name: str,
        value: Any,
        target_type: Any,
        field_path: str,
    ) -> Any:
        current = value
        for transform_entry in cls._get_field_transforms(field_name, "after"):
            current = cls._invoke_transform(
                transform_entry,
                value=current,
                target_type=target_type,
                field_path=field_path,
            )
            if not cls._is_value_compatible_with_annotation(current, target_type):
                raise TransformSettingError(
                    field_name=field_path,
                    mode="after",
                    transform_name=transform_entry.transform_name,
                    target_type=target_type,
                    value_repr=repr(current),
                    reason="after transform changed value to incompatible type",
                )
        return current

    @classmethod
    def _invoke_transform(
        cls,
        transform_entry: _RegisteredTransform,
        *,
        value: Any,
        target_type: Any,
        field_path: str,
    ) -> Any:
        try:
            if transform_entry.takes_cls:
                return transform_entry.func(cls, value)
            return transform_entry.func(value)
        except TransformSettingError:
            raise
        except Exception as exc:
            raise TransformSettingError(
                field_name=field_path,
                mode=transform_entry.mode,
                transform_name=transform_entry.transform_name,
                target_type=target_type,
                raw_value=value if isinstance(value, str) else None,
                value_repr=None if isinstance(value, str) else repr(value),
                reason=f"{type(exc).__name__}: {exc}",
            ) from exc

    @classmethod
    def _is_value_compatible_with_annotation(cls, value: Any, annotation: Any) -> bool:
        target_type = unwrap_annotated(annotation)
        if target_type is Any:
            return True

        origin = get_origin(target_type)
        if origin in {Union, UnionType}:
            return any(
                cls._is_value_compatible_with_annotation(value, option)
                for option in get_args(target_type)
            )

        if value is None:
            return target_type is type(None)

        if origin is not None:
            if isinstance(origin, type):
                return isinstance(value, origin)
            return True

        if isinstance(target_type, type):
            return isinstance(value, target_type)
        return True
