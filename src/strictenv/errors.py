from __future__ import annotations

from typing import Any


class SettingsError(Exception):
    """Base exception for settings loading and parsing errors."""


class EnvFileNotFoundError(SettingsError):
    """Raised when a configured env file path does not exist."""

    def __init__(self, *, env_file: str) -> None:
        """
        Build an error for a missing `.env` file.

        Args:
            env_file: Path configured in `model_config["env_file"]`.
        """
        self.env_file = env_file
        super().__init__(f"Environment file not found: {env_file}")


class EnvFileReadError(SettingsError):
    """Raised when an env file exists but cannot be read."""

    def __init__(self, *, env_file: str, reason: str) -> None:
        """
        Build an error for an env file read/decoding failure.

        Args:
            env_file: Path to the env file that could not be read.
            reason: Human-readable read failure reason.
        """
        self.env_file = env_file
        self.reason = reason
        super().__init__(f"Failed to read environment file {env_file}: {reason}")


class EnvKeyConflictError(SettingsError):
    """Raised when two keys collide in case-insensitive environment mode."""

    def __init__(self, *, normalized_key: str, first_key: str, second_key: str) -> None:
        """
        Build an error for case-insensitive key collisions.

        Args:
            normalized_key: Canonical key used for case-insensitive lookup.
            first_key: First key that mapped to the canonical key.
            second_key: Conflicting key that mapped to the same canonical key.
        """
        self.normalized_key = normalized_key
        self.first_key = first_key
        self.second_key = second_key
        super().__init__(
            "Case-insensitive key collision: "
            f"{first_key!r} and {second_key!r} map to {normalized_key!r}"
        )


class EnvFileFormatError(SettingsError):
    """Raised when an env file line does not match the expected `KEY=VALUE` format."""

    def __init__(
        self,
        *,
        env_file: str,
        line_number: int,
        line: str,
        reason: str,
    ) -> None:
        """
        Build an error for an invalid line in an env file.

        Args:
            env_file: Path to the parsed env file.
            line_number: 1-based line number that failed validation.
            line: Original line content after trimming whitespace.
            reason: Human-readable validation failure reason.
        """
        self.env_file = env_file
        self.line_number = line_number
        self.line = line
        self.reason = reason
        super().__init__(
            f"Invalid env file format in {env_file}:{line_number}: {reason} ({line!r})"
        )


class MissingSettingError(SettingsError):
    """Raised when a required setting is not provided."""

    def __init__(self, *, field_name: str, env_key: str) -> None:
        """
        Build an error for a required field that has no input value.

        Args:
            field_name: Struct field that is missing.
            env_key: Expected environment variable key for that field.
        """
        self.field_name = field_name
        self.env_key = env_key
        super().__init__(f"Missing required setting: {env_key} (field '{field_name}')")


class NestedStructDepthError(SettingsError):
    """Raised when nested `Struct` traversal exceeds the configured depth limit."""

    def __init__(self, *, field_path: str, depth: int, max_depth: int) -> None:
        """
        Build an error for nested struct paths deeper than allowed.

        Args:
            field_path: Dot-like field path that exceeded the limit.
            depth: Current nested depth reached while traversing.
            max_depth: Maximum allowed nested depth from configuration.
        """
        self.field_path = field_path
        self.depth = depth
        self.max_depth = max_depth
        super().__init__(
            "Nested struct depth exceeded: "
            f"path '{field_path}' reached depth {depth}, max allowed is {max_depth}"
        )


class ParseSettingError(SettingsError):
    """Raised when a setting value cannot be parsed into the target type."""

    def __init__(self, *, field_name: str, target_type: Any, raw_value: str) -> None:
        """
        Build an error for a value that cannot be coerced to its target type.

        Args:
            field_name: Field path that failed to parse.
            target_type: Type annotation used for parsing.
            raw_value: Original raw value that failed parsing.
        """
        self.field_name = field_name
        self.target_type = target_type
        self.raw_value = raw_value
        type_name = _type_name(target_type)
        super().__init__(
            f"Failed to parse setting '{field_name}' as {type_name}: {raw_value!r}"
        )


class TransformSettingError(SettingsError):
    """Raised when a field transform cannot be registered or executed."""

    def __init__(
        self,
        *,
        field_name: str,
        mode: str,
        transform_name: str,
        target_type: Any,
        raw_value: str | None = None,
        value_repr: str | None = None,
        reason: str | None = None,
    ) -> None:
        """
        Build an error for transform registration or execution failures.

        Args:
            field_name: Field path associated with the transform.
            mode: Transform mode (`before` or `after`).
            transform_name: Name of the transform callable.
            target_type: Declared target field type.
            raw_value: Optional raw value used as input.
            value_repr: Optional repr of transformed value.
            reason: Optional extra failure details.
        """
        self.field_name = field_name
        self.mode = mode
        self.transform_name = transform_name
        self.target_type = target_type
        self.raw_value = raw_value
        self.value_repr = value_repr
        self.reason = reason

        type_name = _type_name(target_type)
        value_part = (
            f" raw={raw_value!r}"
            if raw_value is not None
            else (f" value={value_repr}" if value_repr is not None else "")
        )
        reason_part = f" ({reason})" if reason else ""
        super().__init__(
            "Transform failure "
            f"[{mode}] '{transform_name}' for field '{field_name}' as {type_name}:"
            f"{value_part}{reason_part}"
        )


def _type_name(target_type: Any) -> str:
    name = getattr(target_type, "__name__", None)
    return name if isinstance(name, str) else repr(target_type)
