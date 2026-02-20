from __future__ import annotations

import pytest
from msgspec import Struct

from strictenv import BaseSettings, TransformSettingError, TransformStruct, transform


class NestedDatabaseConfig(TransformStruct):
    host: str
    port: int

    @transform("host", mode="before")
    def normalize_host(value: str) -> str:
        return value.strip().lower()

    @transform("port", mode="after")
    def increase_port(value: int) -> int:
        return value + 1


class NestedTransformSettings(BaseSettings):
    database: NestedDatabaseConfig

    model_config = {
        "env_nested_delimiter": "__",
    }


class PlainDatabaseConfig(Struct):
    host: str
    port: int


class PlainNestedSettings(BaseSettings):
    database: PlainDatabaseConfig


class BaseNameConfig(TransformStruct):
    name: str

    @transform("name", mode="before")
    def trim_name(value: str) -> str:
        return value.strip()


class ChildNameConfig(BaseNameConfig):
    @transform("name", mode="before")
    def uppercase_name(value: str) -> str:
        return value.upper()


class InheritedTransformSettings(BaseSettings):
    user: ChildNameConfig


class BadNestedConfig(TransformStruct):
    port: int

    @transform("port", mode="after")
    def to_string(value: int) -> str:
        return str(value)


class BadNestedSettings(BaseSettings):
    database: BadNestedConfig


def test_nested_transform_applies_for_env_nested_delimiter() -> None:
    loaded = NestedTransformSettings.load(
        env={
            "DATABASE__HOST": "  LOCALHOST  ",
            "DATABASE__PORT": "5432",
        }
    )
    assert loaded.database.host == "localhost"
    assert loaded.database.port == 5433


def test_nested_transform_applies_for_json_string_input() -> None:
    loaded = NestedTransformSettings.load(
        env={
            "DATABASE": '{"host":"  LOCALHOST  ","port":5432}',
        }
    )
    assert loaded.database.host == "localhost"
    assert loaded.database.port == 5433


def test_nested_transform_applies_for_overrides_dict() -> None:
    loaded = NestedTransformSettings.load(
        env={},
        overrides={
            "database": {
                "host": "  LOCALHOST  ",
                "port": "5432",
            }
        },
    )
    assert loaded.database.host == "localhost"
    assert loaded.database.port == 5433


def test_plain_struct_without_transform_is_unchanged() -> None:
    loaded = PlainNestedSettings.load(
        env={
            "DATABASE": '{"host":"  LOCALHOST  ","port":5432}',
        }
    )
    assert loaded.database.host == "  LOCALHOST  "
    assert loaded.database.port == 5432


def test_plain_struct_works_with_env_nested_delimiter() -> None:
    class PlainNestedDelimiterSettings(BaseSettings):
        database: PlainDatabaseConfig

        model_config = {
            "env_nested_delimiter": "__",
        }

    loaded = PlainNestedDelimiterSettings.load(
        env={
            "DATABASE__HOST": "local",
            "DATABASE__PORT": "5432",
        }
    )
    assert loaded.database.host == "local"
    assert loaded.database.port == 5432


def test_plain_struct_works_with_overrides_dict() -> None:
    loaded = PlainNestedSettings.load(
        env={},
        overrides={
            "database": {
                "host": "local",
                "port": "5432",
            }
        },
    )
    assert loaded.database.host == "local"
    assert loaded.database.port == 5432


def test_transform_struct_inheritance_keeps_parent_then_child_order() -> None:
    loaded = InheritedTransformSettings.load(
        env={
            "USER": '{"name":"  alice  "}',
        }
    )
    assert loaded.user.name == "ALICE"


def test_nested_after_transform_type_violation_raises() -> None:
    with pytest.raises(TransformSettingError):
        BadNestedSettings.load(
            env={
                "DATABASE": '{"port":5432}',
            }
        )
