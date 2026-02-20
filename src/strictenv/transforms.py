from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from typing import Any, Callable, Literal

TransformMode = Literal["before", "after"]

_TRANSFORM_COUNTER = count()
_TRANSFORM_META_ATTR = "__strictenv_transform_meta__"


@dataclass(frozen=True)
class TransformMeta:
    field_name: str
    mode: TransformMode
    order: int


def transform(field_name: str, *, mode: TransformMode) -> Callable[[Any], Any]:
    """
    Register a field transform on a `BaseSettings` or `TransformStruct` class.

    Args:
        field_name: Top-level field name in the class where transform is declared.
        mode: Transform mode (`before` or `after`).

    Returns:
        A decorator that marks a callable as a field transform.
    """
    if not isinstance(field_name, str) or not field_name:
        raise ValueError("transform field_name must be a non-empty string")
    if "." in field_name:
        raise ValueError("transform field_name must be top-level (no dotted paths)")
    if mode not in {"before", "after"}:
        raise ValueError("transform mode must be 'before' or 'after'")

    def decorator(func: Any) -> Any:
        if not callable(func):
            raise TypeError("transform decorator can only be applied to callables")
        meta = TransformMeta(
            field_name=field_name,
            mode=mode,
            order=next(_TRANSFORM_COUNTER),
        )
        setattr(func, _TRANSFORM_META_ATTR, meta)
        return func

    return decorator


def get_transform_meta(candidate: Any) -> TransformMeta | None:
    """Return transform metadata from a callable or descriptor if present."""
    meta = getattr(candidate, _TRANSFORM_META_ATTR, None)
    if isinstance(meta, TransformMeta):
        return meta
    func = getattr(candidate, "__func__", None)
    meta = getattr(func, _TRANSFORM_META_ATTR, None)
    if isinstance(meta, TransformMeta):
        return meta
    return None
