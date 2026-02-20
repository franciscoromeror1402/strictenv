from __future__ import annotations

from typing import Any


class Field:
    """
    Settings field metadata for aliases, defaults, and lightweight validation rules.

    This can be used either:
    - In `typing.Annotated` metadata.
    - As a field default value, e.g. `name: str = Field("default")`.
    """

    __slots__ = (
        "default",
        "alias",
        "description",
        "gt",
        "ge",
        "lt",
        "le",
        "min_length",
        "max_length",
    )

    def __init__(
        self,
        default: Any = ...,
        *,
        alias: str | None = None,
        description: str | None = None,
        gt: int | float | None = None,
        ge: int | float | None = None,
        lt: int | float | None = None,
        le: int | float | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> None:
        """
        Create metadata and validation settings for a field.

        Args:
            default: Default value when used as field default. Use `...` to mark required.
            alias: Optional environment variable name to use instead of the field name.
            description: Human-readable description for docs/metadata.
            gt: Value must be strictly greater than this bound.
            ge: Value must be greater than or equal to this bound.
            lt: Value must be strictly lower than this bound.
            le: Value must be lower than or equal to this bound.
            min_length: Minimum allowed length for sized values.
            max_length: Maximum allowed length for sized values.
        """
        if alias is not None and not alias:
            raise ValueError("Field alias cannot be an empty string")
        if gt is not None and ge is not None:
            raise ValueError("Use either gt or ge, not both")
        if lt is not None and le is not None:
            raise ValueError("Use either lt or le, not both")
        if min_length is not None and min_length < 0:
            raise ValueError("min_length must be >= 0")
        if max_length is not None and max_length < 0:
            raise ValueError("max_length must be >= 0")
        if (
            min_length is not None
            and max_length is not None
            and min_length > max_length
        ):
            raise ValueError("min_length cannot be greater than max_length")

        if gt is not None and lt is not None and not gt < lt:
            raise ValueError("gt must be lower than lt")
        if gt is not None and le is not None and not gt < le:
            raise ValueError("gt must be lower than le")
        if ge is not None and lt is not None and not ge < lt:
            raise ValueError("ge must be lower than lt")
        if ge is not None and le is not None and not ge <= le:
            raise ValueError("ge must be lower than or equal to le")

        self.default = default
        self.alias = alias
        self.description = description
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.min_length = min_length
        self.max_length = max_length

    def is_required(self) -> bool:
        """Return whether this field has no default value (`...`)."""
        return self.default is ...
