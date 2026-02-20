from __future__ import annotations

from typing import Annotated, Any, get_type_hints

import pytest
from msgspec import Meta

from strictenv import BaseSettings, Field, FieldInfo, MissingSettingError, ParseSettingError
from strictenv._coerce import iter_annotated_metadata


def test_field_default_ellipsis_marks_required() -> None:
    class RequiredSettings(BaseSettings):
        token: str = Field(...)

    with pytest.raises(MissingSettingError):
        RequiredSettings.load(env={})


def test_required_field_after_field_default_ellipsis_is_allowed() -> None:
    namespace: dict[str, Any] = {
        "BaseSettings": BaseSettings,
        "Field": Field,
    }
    exec(
        "\n".join(
            [
                "class OrderedRequiredSettings(BaseSettings):",
                "    token: str = Field(...)",
                "    retries: int",
            ]
        ),
        namespace,
    )
    settings_cls = namespace["OrderedRequiredSettings"]

    loaded = settings_cls.load(env={"TOKEN": "abc", "RETRIES": "3"})
    assert loaded.token == "abc"
    assert loaded.retries == 3


def test_field_alias_from_default_value_is_respected() -> None:
    class AliasFromDefaultSettings(BaseSettings):
        tenant_id: str = Field(..., alias="TENANT")

    loaded = AliasFromDefaultSettings.load(env={"TENANT": "acme"})
    assert loaded.tenant_id == "acme"


def test_field_default_value_and_numeric_validations() -> None:
    class NumericRulesSettings(BaseSettings):
        retries: int = Field(3, gt=0, lt=10)

    assert NumericRulesSettings.load(env={}).retries == 3
    assert NumericRulesSettings.load(env={"RETRIES": "7"}).retries == 7

    with pytest.raises(ParseSettingError):
        NumericRulesSettings.load(env={"RETRIES": "0"})
    with pytest.raises(ParseSettingError):
        NumericRulesSettings.load(env={"RETRIES": "10"})


def test_annotated_and_default_field_metadata_are_merged() -> None:
    class MergedFieldSettings(BaseSettings):
        size: Annotated[int, Field(gt=0)] = Field(..., alias="APP_SIZE", lt=10)

    assert MergedFieldSettings.load(env={"APP_SIZE": "5"}).size == 5

    with pytest.raises(ParseSettingError):
        MergedFieldSettings.load(env={"APP_SIZE": "0"})
    with pytest.raises(ParseSettingError):
        MergedFieldSettings.load(env={"APP_SIZE": "10"})


def test_length_validations_apply_to_set_values_and_description_is_stored() -> None:
    class ScopeSettings(BaseSettings):
        scopes: set[str] = Field(..., min_length=1, description="Granted scopes")

    loaded = ScopeSettings.load(env={"SCOPES": '["read","write"]'})
    assert loaded.scopes == {"read", "write"}

    with pytest.raises(ParseSettingError):
        ScopeSettings.load(env={"SCOPES": "[]"})

    default_meta = getattr(ScopeSettings, "__struct_defaults__")[0]
    assert isinstance(default_meta, FieldInfo)
    assert default_meta.description == "Granted scopes"


def _meta_description_for_field(struct_type: type[BaseSettings], field_name: str) -> str | None:
    annotation = get_type_hints(struct_type, include_extras=True)[field_name]
    _, metadata = iter_annotated_metadata(annotation)
    for item in metadata:
        if isinstance(item, Meta):
            return item.description
    return None


def test_field_description_is_injected_into_msgspec_meta() -> None:
    class FieldDescriptionSettings(BaseSettings):
        token: str = Field(..., description="Token from field metadata")

    FieldDescriptionSettings._get_declared_fields(FieldDescriptionSettings)
    assert _meta_description_for_field(FieldDescriptionSettings, "token") == (
        "Token from field metadata"
    )


def test_attribute_docstring_is_used_as_meta_description() -> None:
    class DocDescriptionSettings(BaseSettings):
        token: str
        """Token from attribute docstring."""

    DocDescriptionSettings._get_declared_fields(DocDescriptionSettings)
    assert _meta_description_for_field(DocDescriptionSettings, "token") == (
        "Token from attribute docstring."
    )


def test_field_description_has_priority_over_attribute_docstring() -> None:
    class PriorityDescriptionSettings(BaseSettings):
        token: str = Field(..., description="Token from field")
        """Token from docstring."""

    PriorityDescriptionSettings._get_declared_fields(PriorityDescriptionSettings)
    assert _meta_description_for_field(PriorityDescriptionSettings, "token") == "Token from field"
