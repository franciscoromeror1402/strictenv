from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import UnionType
from typing import Any, ClassVar, TypeVar, Union, get_args, get_origin

from msgspec import NODEFAULT, Struct, StructMeta

from ._coerce import (
    extract_struct_type,
    field_info,
    get_annotations,
    unwrap_annotated,
    validate_constraints,
)
from .errors import TransformSettingError
from .transforms import (
    TransformMode,
    get_struct_transform_meta,
    get_transform_meta,
)


@dataclass(frozen=True)
class _RegisteredTransform:
    field_name: str
    mode: TransformMode
    transform_name: str
    func: Any
    takes_cls: bool
    order: int


TransformRegistry = dict[str, dict[TransformMode, list[_RegisteredTransform]]]


@dataclass(frozen=True)
class _RegisteredStructTransform:
    transform_name: str
    func: Any
    takes_cls: bool
    order: int


StructTransformRegistry = list[_RegisteredStructTransform]
TTransformStruct = TypeVar("TTransformStruct", bound="TransformStruct")


class _TransformStructMeta(StructMeta):
    def __new__(
        mcls,
        name: str,
        bases: tuple[type[Any], ...],
        ns: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        kwargs.setdefault("kw_only", True)
        return super().__new__(mcls, name, bases, ns, **kwargs)


class TransformStruct(Struct, metaclass=_TransformStructMeta):
    """
    `msgspec.Struct` subclass with field and struct transforms.

    Field transforms are declared with `@transform("field", mode="before" | "after")`.
    Struct transforms are declared with `@transform_struct`.
    """

    __field_transforms__: ClassVar[TransformRegistry] = {}
    __struct_transforms__: ClassVar[StructTransformRegistry] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        field_registry = cls._clone_inherited_transform_registry()
        declared_field_transforms = cls._collect_declared_transforms()

        for transform_entry in declared_field_transforms:
            cls._remove_transform_name(field_registry, transform_entry.transform_name)
            field_transforms = field_registry.setdefault(
                transform_entry.field_name,
                {"before": [], "after": []},
            )
            field_transforms[transform_entry.mode].append(transform_entry)

        cls.__field_transforms__ = field_registry

        struct_registry = cls._clone_inherited_struct_transform_registry()
        declared_struct_transforms = cls._collect_declared_struct_transforms()
        for struct_transform_entry in declared_struct_transforms:
            cls._remove_struct_transform_name(
                struct_registry,
                struct_transform_entry.transform_name,
            )
            struct_registry.append(struct_transform_entry)
        cls.__struct_transforms__ = struct_registry

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
    def _clone_inherited_struct_transform_registry(cls) -> StructTransformRegistry:
        cloned: StructTransformRegistry = []
        for base in reversed(cls.__mro__[1:]):
            base_registry = getattr(base, "__struct_transforms__", None)
            if not base_registry:
                continue
            cloned.extend(base_registry)
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
    def _collect_declared_struct_transforms(cls) -> list[_RegisteredStructTransform]:
        declared: list[_RegisteredStructTransform] = []

        for attr_name, attr_value in cls.__dict__.items():
            meta = get_struct_transform_meta(attr_value)
            if meta is None:
                continue

            if isinstance(attr_value, (classmethod, staticmethod)):
                func = attr_value.__func__
            else:
                func = attr_value
            takes_cls = cls._resolve_struct_transform_signature(func, attr_name=attr_name)
            declared.append(
                _RegisteredStructTransform(
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
        return set(cls._get_declared_struct_fields())

    @classmethod
    def _get_declared_struct_fields(cls) -> dict[str, Any]:
        annotations = get_annotations(cls)
        declared: dict[str, Any] = {}
        for field_name, field_type in annotations.items():
            if field_name == "model_config":
                continue
            if get_origin(field_type) is ClassVar:
                continue
            declared[field_name] = field_type
        return declared

    @classmethod
    def _get_own_struct_default(cls, field_name: str) -> tuple[bool, Any]:
        fields = cls.__struct_fields__
        defaults = cls.__struct_defaults__
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
    def _resolve_positional_signature(
        cls,
        func: Any,
        *,
        field_name: str,
        mode: str,
        transform_name: str,
        invalid_reason: str,
    ) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError) as exc:
            raise TransformSettingError(
                field_name=field_name,
                mode=mode,
                transform_name=transform_name,
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
            field_name=field_name,
            mode=mode,
            transform_name=transform_name,
            target_type=Any,
            value_repr=repr(func),
            reason=invalid_reason,
        )

    @classmethod
    def _resolve_transform_signature(
        cls,
        func: Any,
        *,
        meta: Any,
        attr_name: str,
    ) -> bool:
        return cls._resolve_positional_signature(
            func,
            field_name=meta.field_name,
            mode=meta.mode,
            transform_name=attr_name,
            invalid_reason="transform must accept (value) or (cls, value)",
        )

    @classmethod
    def _resolve_struct_transform_signature(
        cls,
        func: Any,
        *,
        attr_name: str,
    ) -> bool:
        return cls._resolve_positional_signature(
            func,
            field_name=cls.__name__,
            mode="struct_after",
            transform_name=attr_name,
            invalid_reason="transform_struct must accept (instance) or (cls, instance)",
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

    @staticmethod
    def _remove_struct_transform_name(
        registry: StructTransformRegistry, transform_name: str
    ) -> None:
        registry[:] = [item for item in registry if item.transform_name != transform_name]

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
    def _apply_struct_transforms(
        cls: type[TTransformStruct],
        instance: TTransformStruct,
        *,
        field_path: str,
    ) -> TTransformStruct:
        if not isinstance(instance, cls):
            raise TransformSettingError(
                field_name=field_path or cls.__name__,
                mode="struct_after",
                transform_name="<struct-transform-chain>",
                target_type=cls,
                value_repr=repr(instance),
                reason="struct transform target is not an instance of the declaring class",
            )

        for transform_entry in cls.__struct_transforms__:
            try:
                if transform_entry.takes_cls:
                    result = transform_entry.func(cls, instance)
                else:
                    result = transform_entry.func(instance)
            except TransformSettingError:
                raise
            except Exception as exc:
                raise TransformSettingError(
                    field_name=field_path or cls.__name__,
                    mode="struct_after",
                    transform_name=transform_entry.transform_name,
                    target_type=cls,
                    value_repr=repr(instance),
                    reason=f"{type(exc).__name__}: {exc}",
                ) from exc

            if result is not None:
                raise TransformSettingError(
                    field_name=field_path or cls.__name__,
                    mode="struct_after",
                    transform_name=transform_entry.transform_name,
                    target_type=cls,
                    value_repr=repr(result),
                    reason="transform_struct must mutate in place and return None",
                )

        cls._revalidate_struct_instance(instance, field_path=field_path)
        return instance

    @classmethod
    def _revalidate_struct_instance(
        cls,
        instance: Any,
        *,
        field_path: str,
    ) -> None:
        annotations = cls._get_declared_struct_fields()
        for field_name, field_type in annotations.items():
            current_path = f"{field_path}.{field_name}" if field_path else field_name
            value = getattr(instance, field_name)

            if not cls._is_value_compatible_with_annotation(value, field_type):
                raise TransformSettingError(
                    field_name=current_path,
                    mode="struct_after",
                    transform_name="<struct-transform-chain>",
                    target_type=field_type,
                    value_repr=repr(value),
                    reason="transform_struct changed value to incompatible type",
                )

            has_default, raw_default = cls._get_own_struct_default(field_name)
            info = field_info(field_type, default=raw_default if has_default else None)
            validate_constraints(
                value,
                unwrap_annotated(field_type),
                field_name=current_path,
                field=info,
                raw_value=repr(value),
            )

            nested_struct = extract_struct_type(field_type)
            if (
                nested_struct is not None
                and isinstance(nested_struct, type)
                and issubclass(nested_struct, TransformStruct)
                and isinstance(value, nested_struct)
            ):
                nested_struct._revalidate_struct_instance(value, field_path=current_path)

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
