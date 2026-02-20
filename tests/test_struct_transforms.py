from __future__ import annotations

from typing import Any

import pytest

from strictenv import (
    BaseSettings,
    Field,
    ParseSettingError,
    TransformSettingError,
    TransformStruct,
    transform_struct,
)


class RootStructTransformSettings(BaseSettings):
    count: int
    name: str

    @classmethod
    @transform_struct
    def normalize(cls, instance: Any) -> None:
        assert cls is RootStructTransformSettings
        instance.count += 1
        instance.name = instance.name.strip().lower()


class NestedDatabaseStruct(TransformStruct):
    host: str
    port: int

    @transform_struct
    def normalize(instance: Any) -> None:
        instance.host = instance.host.strip().lower()
        instance.port += 1


class NestedStructTransformSettings(BaseSettings):
    database: NestedDatabaseStruct


class BadTypeStruct(TransformStruct):
    count: int

    @transform_struct
    def break_type(instance: Any) -> None:
        instance.count = "bad"


class BadTypeSettings(BaseSettings):
    payload: BadTypeStruct


class ConstrainedStructTransformSettings(BaseSettings):
    token: str = Field(..., min_length=4)

    @transform_struct
    def shrink(instance: Any) -> None:
        instance.token = "abc"


INHERIT_CALLS: list[str] = []


class ParentStructTransform(TransformStruct):
    value: str

    @transform_struct
    def parent(instance: Any) -> None:
        INHERIT_CALLS.append("parent")
        instance.value = f"{instance.value}-p"


class ChildStructTransform(ParentStructTransform):
    @transform_struct
    def child(instance: Any) -> None:
        INHERIT_CALLS.append("child")
        instance.value = f"{instance.value}-c"


class InheritedStructTransformSettings(BaseSettings):
    payload: ChildStructTransform


class ParentOverrideTransform(TransformStruct):
    value: str

    @transform_struct
    def mutate(instance: Any) -> None:
        instance.value = f"{instance.value}-parent"


class ChildOverrideTransform(ParentOverrideTransform):
    @transform_struct
    def mutate(instance: Any) -> None:
        instance.value = f"{instance.value}-child"


class OverrideStructTransformSettings(BaseSettings):
    payload: ChildOverrideTransform


class InvalidReturnStructTransformSettings(BaseSettings):
    value: int

    @transform_struct
    def invalid(instance: Any) -> object:
        return instance


def test_struct_transform_applies_on_root_settings_instance() -> None:
    loaded = RootStructTransformSettings.load(
        env={
            "COUNT": "41",
            "NAME": "  Alice  ",
        }
    )
    assert loaded.count == 42
    assert loaded.name == "alice"


def test_struct_transform_applies_on_nested_transform_struct() -> None:
    loaded = NestedStructTransformSettings.load(
        env={
            "DATABASE": '{"host":"  LOCALHOST  ","port":5432}',
        }
    )
    assert loaded.database.host == "localhost"
    assert loaded.database.port == 5433


def test_struct_transform_rejects_type_change() -> None:
    with pytest.raises(TransformSettingError):
        BadTypeSettings.load(
            env={
                "PAYLOAD": '{"count":1}',
            }
        )


def test_struct_transform_revalidates_constraints_after_mutation() -> None:
    with pytest.raises(ParseSettingError):
        ConstrainedStructTransformSettings.load(env={"TOKEN": "abcdef"})


def test_struct_transform_registration_fails_for_invalid_signature() -> None:
    with pytest.raises(TransformSettingError):

        class InvalidStructTransformSignature(BaseSettings):
            value: int

            @transform_struct
            def invalid(cls, instance: Any, extra: object) -> None:
                _ = cls
                _ = instance
                _ = extra


def test_struct_transform_inheritance_keeps_parent_then_child_order() -> None:
    INHERIT_CALLS.clear()
    loaded = InheritedStructTransformSettings.load(env={"PAYLOAD": '{"value":"x"}'})
    assert INHERIT_CALLS == ["parent", "child"]
    assert loaded.payload.value == "x-p-c"


def test_struct_transform_inheritance_allows_override_by_method_name() -> None:
    loaded = OverrideStructTransformSettings.load(env={"PAYLOAD": '{"value":"x"}'})
    assert loaded.payload.value == "x-child"


def test_struct_transform_must_return_none() -> None:
    with pytest.raises(TransformSettingError):
        InvalidReturnStructTransformSettings.load(env={"VALUE": "1"})
