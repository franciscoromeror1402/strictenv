from __future__ import annotations

import pytest
from msgspec import Struct

from strictenv import BaseSettings, NestedStructDepthError


class Credentials(Struct):
    username: str


class Database(Struct):
    host: str
    credentials: Credentials


class NestedSettings(BaseSettings):
    database: Database

    model_config = {
        "env_nested_delimiter": "__",
    }


def test_nested_env_two_and_three_levels() -> None:
    loaded = NestedSettings.load(
        env={
            "DATABASE__HOST": "localhost",
            "DATABASE__CREDENTIALS__USERNAME": "alice",
        }
    )
    assert loaded.database.host == "localhost"
    assert loaded.database.credentials.username == "alice"


class DeepCredentials(Struct):
    username: str


class DeepDatabase(Struct):
    host: str
    credentials: DeepCredentials


class LimitedDepthSettings(BaseSettings):
    database: DeepDatabase

    model_config = {
        "env_nested_delimiter": "__",
        "max_nested_struct_depth": 1,
    }


def test_nested_unknown_variables_are_ignored() -> None:
    loaded = NestedSettings.load(
        env={
            "DATABASE__HOST": "localhost",
            "DATABASE__CREDENTIALS__USERNAME": "alice",
            "DATABASE__CREDENTIALS__UNKNOWN": "noop",
            "DATABASE__UNKNOWN__FIELD": "noop",
        }
    )
    assert loaded.database.credentials.username == "alice"


def test_nested_struct_depth_limit_raises_for_nested_env() -> None:
    with pytest.raises(NestedStructDepthError):
        LimitedDepthSettings.load(
            env={
                "DATABASE__HOST": "localhost",
                "DATABASE__CREDENTIALS__USERNAME": "alice",
            }
        )


def test_nested_struct_depth_limit_raises_for_overrides_dict() -> None:
    with pytest.raises(NestedStructDepthError):
        LimitedDepthSettings.load(
            env={},
            overrides={
                "database": {
                    "host": "localhost",
                    "credentials": {"username": "alice"},
                }
            },
        )
