from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Mapping

import pytest
from msgspec import Struct

from strictenv import BaseSettings, ParseSettingError


class ServiceMode(Enum):
    DEV = "dev"
    PROD = "prod"


class DbConfig(Struct):
    host: str
    port: int


class TypesSettings(BaseSettings):
    enabled: bool
    numeric_union: int | float
    mode: ServiceMode
    db: DbConfig
    optional_port: int | None = None


class RichTypesSettings(BaseSettings):
    tags: list[str]
    metadata: dict[str, int]
    options: Mapping[str, str]
    scopes: set[str]
    created_at: datetime
    business_date: date
    at_time: time
    timeout: timedelta


def test_bool_optional_union_enum_and_struct_parsing() -> None:
    loaded = TypesSettings.load(
        env={
            "ENABLED": "yes",
            "NUMERIC_UNION": "3.14",
            "MODE": "DEV",
            "DB": '{"host":"localhost","port":5432}',
        }
    )
    assert loaded.enabled is True
    assert loaded.optional_port is None
    assert loaded.numeric_union == pytest.approx(3.14)
    assert loaded.mode is ServiceMode.DEV
    assert loaded.db.host == "localhost"
    assert loaded.db.port == 5432


def test_enum_parses_from_value() -> None:
    loaded = TypesSettings.load(
        env={
            "ENABLED": "true",
            "NUMERIC_UNION": "1",
            "MODE": "prod",
            "DB": '{"host":"localhost","port":5432}',
        }
    )
    assert loaded.mode is ServiceMode.PROD


def test_invalid_bool_raises_parse_error() -> None:
    with pytest.raises(ParseSettingError):
        TypesSettings.load(
            env={
                "ENABLED": "not-a-bool",
                "NUMERIC_UNION": "1",
                "MODE": "DEV",
                "DB": '{"host":"localhost","port":5432}',
            }
        )


def test_collection_datetime_and_timedelta_parsing() -> None:
    loaded = RichTypesSettings.load(
        env={
            "TAGS": '["api","worker"]',
            "METADATA": '{"workers":2,"retries":5}',
            "OPTIONS": '{"region":"eu-west-1"}',
            "SCOPES": '["read","write","read"]',
            "CREATED_AT": "2026-02-19T09:30:00Z",
            "BUSINESS_DATE": "2026-02-19",
            "AT_TIME": "09:30:45",
            "TIMEOUT": "PT1H15M",
        }
    )
    assert loaded.tags == ["api", "worker"]
    assert loaded.metadata == {"workers": 2, "retries": 5}
    assert loaded.options == {"region": "eu-west-1"}
    assert loaded.scopes == {"read", "write"}
    assert loaded.created_at.isoformat() == "2026-02-19T09:30:00+00:00"
    assert loaded.business_date == date(2026, 2, 19)
    assert loaded.at_time == time(9, 30, 45)
    assert loaded.timeout == timedelta(hours=1, minutes=15)


def test_timedelta_accepts_seconds_and_clock_formats() -> None:
    class DurationSettings(BaseSettings):
        timeout: timedelta

    seconds = DurationSettings.load(env={"TIMEOUT": "90"})
    assert seconds.timeout == timedelta(seconds=90)

    clock = DurationSettings.load(env={"TIMEOUT": "01:02:03"})
    assert clock.timeout == timedelta(hours=1, minutes=2, seconds=3)


def test_invalid_temporal_values_raise_parse_error() -> None:
    class TemporalSettings(BaseSettings):
        created_at: datetime
        timeout: timedelta

    with pytest.raises(ParseSettingError):
        TemporalSettings.load(env={"CREATED_AT": "not-a-datetime", "TIMEOUT": "PT1H"})

    with pytest.raises(ParseSettingError):
        TemporalSettings.load(
            env={"CREATED_AT": "2026-02-19T09:30:00Z", "TIMEOUT": "not-a-duration"}
        )
