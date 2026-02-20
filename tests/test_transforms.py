from __future__ import annotations

import pytest

from strictenv import BaseSettings, Field, ParseSettingError, TransformSettingError, transform


class TopLevelTransformSettings(BaseSettings):
    count: int
    enabled: bool
    name: str = Field(..., min_length=3)

    @transform("name", mode="before")
    def normalize_name(value: str) -> str:
        return value.strip().lower()

    @transform("count", mode="before")
    def parse_count(value: str) -> int:
        return int(value) + 1

    @transform("enabled", mode="after")
    def invert_enabled(value: bool) -> bool:
        return not value


def test_before_and_after_transforms_apply_on_top_level_fields() -> None:
    loaded = TopLevelTransformSettings.load(
        env={
            "NAME": "  Alice  ",
            "COUNT": "41",
            "ENABLED": "true",
        }
    )
    assert loaded.name == "alice"
    assert loaded.count == 42
    assert loaded.enabled is False


def test_multiple_transforms_keep_definition_order() -> None:
    class OrderedTransformSettings(BaseSettings):
        value: str

        @transform("value", mode="before")
        def strip_spaces(value: str) -> str:
            return value.strip()

        @transform("value", mode="before")
        def append_suffix(value: str) -> str:
            return f"{value}-suffix"

    loaded = OrderedTransformSettings.load(env={"VALUE": "  hello  "})
    assert loaded.value == "hello-suffix"


def test_after_transform_must_keep_type() -> None:
    class BadAfterTransformSettings(BaseSettings):
        count: int

        @transform("count", mode="after")
        def as_text(value: int) -> str:
            return str(value)

    with pytest.raises(TransformSettingError):
        BadAfterTransformSettings.load(env={"COUNT": "5"})


def test_transform_registration_fails_for_unknown_field() -> None:
    with pytest.raises(TransformSettingError):
        class InvalidTransformFieldSettings(BaseSettings):
            count: int

            @transform("unknown", mode="before")
            def transform_unknown(value: str) -> str:
                return value


def test_before_transform_integrates_with_constraints() -> None:
    class ConstrainedTransformSettings(BaseSettings):
        token: str = Field(..., min_length=4)

        @transform("token", mode="before")
        def trim_token(value: str) -> str:
            return value.strip()

    with pytest.raises(ParseSettingError):
        ConstrainedTransformSettings.load(env={"TOKEN": "  abc  "})


def test_after_transform_integrates_with_constraints() -> None:
    class ConstrainedAfterTransformSettings(BaseSettings):
        count: int = Field(..., gt=10)

        @transform("count", mode="after")
        def decrease_count(value: int) -> int:
            return value - 20

    with pytest.raises(ParseSettingError):
        ConstrainedAfterTransformSettings.load(env={"COUNT": "25"})
