# strictenv

`strictenv` is a fast, strictly typed environment variable loader built on top of `msgspec`.
It gives you explicit schemas, predictable coercion, and runtime validation with a small API.

## Install

```bash
uv add strictenv
```

## Quickstart

```python
from __future__ import annotations

from typing import Annotated

from msgspec import Struct

from strictenv import BaseSettings, Field, TransformStruct, transform


class Database(TransformStruct):
    host: str
    port: int

    @transform("host", mode="before")
    def normalize_host(value: str) -> str:
        return value.strip().lower()


class AppSettings(BaseSettings):
    debug: bool
    database: Database
    tenant_id: Annotated[str, Field(alias="TENANT")]

    model_config = {
        "env_prefix": "APP_",
        "case_sensitive": False,
        "env_nested_delimiter": "__",
        "env_file": ".env",
        "strict_env_file": True,
    }


settings = AppSettings.load()
AppSettings.write_env_example(".env.example")
```

Examples:
- `APP_DEBUG=true` -> `debug: bool`
- `APP_DATABASE={"host":"localhost","port":5432}` -> `database: Database`
- `APP_DATABASE__HOST=localhost` + `APP_DATABASE__PORT=5432` -> nested parsing
- `APP_TENANT=acme` -> `tenant_id` via alias

## `model_config`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `env_prefix` | `str` | `""` | Prefix applied to all environment keys. |
| `case_sensitive` | `bool` | `False` | When `False`, key lookup is case-insensitive. |
| `env_nested_delimiter` | `str \| None` | `None` | Enables nested mapping like `DB__HOST`. |
| `env_file` | `str \| None` | `None` | Path to a `.env` file to load first. |
| `strict_env_file` | `bool` | `True` | When `True`, invalid/missing `.env` files raise explicit errors. |
| `max_nested_struct_depth` | `int \| None` | `None` | Maximum allowed depth for nested `Struct` traversal. |

## `Field(...)`

`Field` works both in `Annotated[...]` and as a default value:

```python
from typing import Annotated
from strictenv import BaseSettings, Field

class AppSettings(BaseSettings):
    # Annotated metadata style
    retries: Annotated[int, Field(gt=0, lt=10)]

    # Default value style (alias + default + description)
    tenant_id: str = Field("acme", alias="TENANT", description="Tenant identifier")

    # Required when using `...`
    token: str = Field(...)
```

Supported quick validations:
- `gt`, `ge`, `lt`, `le`
- `min_length`, `max_length`

Description source priority for metadata/examples:
- `Field(description=...)` (highest priority)
- attribute docstring right below the field

## `@transform(...)` And `TransformStruct`

Use `@transform(field_name, mode="before" | "after")` on classes that inherit
from `TransformStruct` (including `BaseSettings`).

- `before` receives raw string input and may return:
  - another `str` (then normal coercion runs), or
  - a value already in target type.
- `after` receives already parsed value and must keep a compatible runtime type.

```python
from strictenv import BaseSettings, TransformStruct, transform, transform_struct

class DatabaseConfig(TransformStruct):
    host: str
    port: int

    @transform("host", mode="before")
    def normalize_host(value: str) -> str:
        return value.strip().lower()

    @transform("port", mode="after")
    def keep_int(value: int) -> int:
        return value + 1

class AppSettings(BaseSettings):
    database: DatabaseConfig
```

Rules:
- `field_name` must be top-level in that class (no dotted paths).
- Multiple transforms run in definition order.
- Nested transforms apply only when nested type inherits `TransformStruct`.
- Nested settings can still use plain `msgspec.Struct`; use `TransformStruct` only when you need `@transform`.

## `@transform_struct(...)`

Use `@transform_struct` when you need to mutate the already-built struct instance.

```python
from strictenv import BaseSettings, Field, transform_struct

class AppSettings(BaseSettings):
    token: str = Field(..., min_length=4)

    @transform_struct
    def normalize(instance: AppSettings) -> None:
        instance.token = instance.token.strip().lower()
```

Execution order:
- `before` field transforms
- parse/coerce
- `after` field transforms
- `transform_struct`
- final revalidation (runtime type compatibility + field constraints)

Notes:
- `transform_struct` applies to any `TransformStruct` (root and nested).
- The hook must mutate in place and return `None`.
- Changing an attribute to an incompatible type raises `TransformSettingError`.

## Generate `.env.example`

`BaseSettings.write_env_example(path)` writes an empty env template for the schema.
Field descriptions are emitted as comments:

```python
class AppSettings(BaseSettings):
    debug: bool = Field(..., description="Enable debug logs")
    tenant_id: str = Field(..., alias="TENANT", description="Tenant identifier")

AppSettings.write_env_example(".env.example")
```

Generated file:

```dotenv
# Enable debug logs
DEBUG=

# Tenant identifier
TENANT=
```

## Value precedence

1. `overrides` argument in `load(...)`
2. `env` argument (or `os.environ` when `env=None`)
3. `.env` file configured with `model_config["env_file"]`
4. Field defaults in the settings struct

If no source provides a required field, `MissingSettingError` is raised.
If `env_file` is configured but missing, `EnvFileNotFoundError` is raised.
If `env_file` cannot be read, `EnvFileReadError` is raised.
If a non-comment line in `env_file` is not valid `KEY=VALUE`, `EnvFileFormatError` is raised.
If keys collide in case-insensitive mode, `EnvKeyConflictError` is raised.
If nested struct depth exceeds `max_nested_struct_depth`, `NestedStructDepthError` is raised.
With `strict_env_file=False`, `.env` file errors are tolerated and invalid lines are skipped.

## Coercion rules

`strictenv` performs strict coercion for:
- `bool`, `int`, `float`, `str`
- `Enum` (by member name or value)
- `datetime`, `date`, `time`
- `timedelta` (ISO8601, `HH:MM[:SS]`, or numeric seconds)
- `msgspec.Struct` (from JSON string)
- `list`, `dict`, `tuple`, `set`, `Mapping` (from JSON string)
- `Union` / `Optional` (tries non-`None` members in order)

Invalid values raise `ParseSettingError`. There is no silent fallback to raw strings.
Transform registration/execution failures raise `TransformSettingError`.

`.env` parser features:
- Optional `export` prefix (`export KEY=value`)
- Inline comments for unquoted values (`KEY=value # comment`)
- Quoted values with escapes and multiline support
- Variable expansion via `${VAR}` (including references to earlier/later keys)

## Differences vs `pydantic-settings`

- API is intentionally smaller and focused on `msgspec.Struct`.
- Compatibility is partial (supports familiar `model_config`, aliases, and nested env parsing).
- Automatic field description injection into `msgspec.Meta` is supported.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run mypy src
uv run pytest
uv build
```

## Contributing

See `CONTRIBUTING.md` for PR workflow, checks, and contribution guidelines.

## Release (Maintainers)

Publishing is maintainer-only and handled by GitHub Actions on version tags.

Typical flow:

```bash
# 1) bump version in pyproject.toml and update CHANGELOG.md
git tag vX.Y.Z
git push origin vX.Y.Z
```
