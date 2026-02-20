from __future__ import annotations

import pytest

from strictenv import (
    BaseSettings,
    EnvFileFormatError,
    EnvFileNotFoundError,
    EnvFileReadError,
    EnvKeyConflictError,
    MissingSettingError,
    ParseSettingError,
)


class MissingSettings(BaseSettings):
    token: str


def test_missing_required_setting_error_contains_field_and_env_key() -> None:
    with pytest.raises(MissingSettingError) as exc_info:
        MissingSettings.load(env={})

    err = exc_info.value
    assert err.field_name == "token"
    assert err.env_key == "TOKEN"


class ParseSettings(BaseSettings):
    count: int


def test_parse_setting_error_contains_context() -> None:
    with pytest.raises(ParseSettingError) as exc_info:
        ParseSettings.load(env={"COUNT": "abc"})

    err = exc_info.value
    assert err.field_name == "count"
    assert err.raw_value == "abc"


def test_env_file_not_found_error_contains_path() -> None:
    class MissingEnvFileSettings(BaseSettings):
        value: str = "default"
        model_config = {"env_file": "does-not-exist.env"}

    with pytest.raises(EnvFileNotFoundError) as exc_info:
        MissingEnvFileSettings.load(env={})

    err = exc_info.value
    assert err.env_file == "does-not-exist.env"


def test_env_file_format_error_contains_line_context(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OK=value\nINVALID_LINE\n", encoding="utf-8")

    class InvalidEnvFormatSettings(BaseSettings):
        ok: str
        model_config = {"env_file": str(env_file)}

    with pytest.raises(EnvFileFormatError) as exc_info:
        InvalidEnvFormatSettings.load(env={})

    err = exc_info.value
    assert err.env_file == str(env_file)
    assert err.line_number == 2
    assert err.line == "INVALID_LINE"


def test_env_file_read_error_for_unreadable_path(tmp_path) -> None:
    env_dir = tmp_path / "envdir"
    env_dir.mkdir()

    class UnreadableEnvFileSettings(BaseSettings):
        value: str = "default"
        model_config = {"env_file": str(env_dir)}

    with pytest.raises(EnvFileReadError) as exc_info:
        UnreadableEnvFileSettings.load(env={})

    err = exc_info.value
    assert err.env_file == str(env_dir)


def test_non_strict_env_file_ignores_missing_file() -> None:
    class NonStrictMissingEnvFileSettings(BaseSettings):
        value: str = "default"
        model_config = {
            "env_file": "does-not-exist.env",
            "strict_env_file": False,
        }

    loaded = NonStrictMissingEnvFileSettings.load(env={})
    assert loaded.value == "default"


def test_non_strict_env_file_skips_invalid_lines_and_keeps_last_duplicate(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "VALID=ok",
                "INVALID_LINE",
                "=empty_key",
                "A-B=invalid_name",
                "DUP=first",
                "DUP=second",
            ]
        ),
        encoding="utf-8",
    )

    class NonStrictMalformedEnvFileSettings(BaseSettings):
        valid: str
        dup: str
        model_config = {
            "env_file": str(env_file),
            "strict_env_file": False,
        }

    loaded = NonStrictMalformedEnvFileSettings.load(env={})
    assert loaded.valid == "ok"
    assert loaded.dup == "second"


def test_case_insensitive_collision_raises_in_strict_mode() -> None:
    class CaseCollisionSettings(BaseSettings):
        debug: bool

    with pytest.raises(EnvKeyConflictError):
        CaseCollisionSettings.load(env={"debug": "true", "DEBUG": "false"})


def test_invalid_max_nested_struct_depth_configuration_raises_value_error() -> None:
    class InvalidDepthSettings(BaseSettings):
        debug: bool
        model_config = {"max_nested_struct_depth": 0}

    with pytest.raises(ValueError):
        InvalidDepthSettings.load(env={"DEBUG": "true"})
