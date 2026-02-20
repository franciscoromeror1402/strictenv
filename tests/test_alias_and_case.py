from __future__ import annotations

from typing import Annotated

import pytest

from strictenv import BaseSettings, Field, MissingSettingError


class AliasSettings(BaseSettings):
    tenant_id: Annotated[str, Field(alias="TENANT")]


def test_alias_is_checked_before_field_name() -> None:
    loaded = AliasSettings.load(env={"TENANT": "alias-value", "TENANT_ID": "field-value"})
    assert loaded.tenant_id == "alias-value"


class CaseSensitiveSettings(BaseSettings):
    debug: bool

    model_config = {
        "case_sensitive": True,
    }


def test_case_sensitive_requires_exact_match() -> None:
    with pytest.raises(MissingSettingError):
        CaseSensitiveSettings.load(env={"DEBUG": "true"})

    loaded = CaseSensitiveSettings.load(env={"debug": "true"})
    assert loaded.debug is True


class CaseInsensitiveSettings(BaseSettings):
    debug: bool


def test_case_insensitive_matches_upper_and_lower() -> None:
    assert CaseInsensitiveSettings.load(env={"debug": "true"}).debug is True
    assert CaseInsensitiveSettings.load(env={"DEBUG": "true"}).debug is True
