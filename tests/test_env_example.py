from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from msgspec import Struct

from strictenv import BaseSettings, Field, NestedStructDepthError


class _ExampleCredentials(Struct):
    username: Annotated[str, Field(description="Database username")]


class _ExampleDatabase(Struct):
    host: Annotated[str, Field(description="Database host")]
    credentials: _ExampleCredentials


class _ExampleNestedSettings(BaseSettings):
    database: _ExampleDatabase = Field(..., description="Database settings")

    model_config = {
        "env_prefix": "APP_",
        "env_nested_delimiter": "__",
    }


class _LimitedExampleNestedSettings(BaseSettings):
    database: _ExampleDatabase = Field(..., description="Database settings")

    model_config = {
        "env_prefix": "APP_",
        "env_nested_delimiter": "__",
        "max_nested_struct_depth": 1,
    }


def test_write_env_example_with_descriptions_and_alias(tmp_path: Path) -> None:
    env_file = tmp_path / "configs" / ".env.example"

    class ExampleSettings(BaseSettings):
        debug: bool = Field(..., description="Enable debug mode")
        tenant_id: str = Field(..., alias="TENANT", description="Tenant identifier")
        retries: int = 3

        model_config = {"env_prefix": "APP_"}

    ExampleSettings.write_env_example(str(env_file))
    content = env_file.read_text(encoding="utf-8")

    expected = "\n".join(
        [
            "# Enable debug mode",
            "APP_DEBUG=",
            "",
            "# Tenant identifier",
            "APP_TENANT=",
            "",
            "APP_RETRIES=",
            "",
        ]
    )
    assert content == expected


def test_write_env_example_for_nested_struct_uses_delimiter(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.example"
    _ExampleNestedSettings.write_env_example(str(env_file))
    content = env_file.read_text(encoding="utf-8")

    expected = "\n".join(
        [
            "# Database host",
            "APP_DATABASE__HOST=",
            "",
            "# Database username",
            "APP_DATABASE__CREDENTIALS__USERNAME=",
            "",
        ]
    )
    assert content == expected


def test_write_env_example_raises_when_nested_depth_limit_is_exceeded(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.example"

    with pytest.raises(NestedStructDepthError):
        _LimitedExampleNestedSettings.write_env_example(str(env_file))
