# Changelog

All notable changes to this project will be documented in this file.

## [0.1.2] - 2026-02-20

### Changed
- `Field(...)` now follows a pydantic-like typed API by exposing `Field` as a function and keeping metadata in `FieldInfo` internally.
- `TransformStruct` now defaults subclasses to keyword-only construction, allowing required fields to be declared after `= Field(...)` without class-definition errors.
- Default detection now handles `msgspec.NODEFAULT` placeholders correctly when resolving required vs optional fields.

### Fixed
- Full `mypy` pass for all test files (`uv run mypy tests`) by adding missing fixture annotations and removing typing edge cases.
- Added regression coverage for field-ordering with `Field(...)` required markers.

## [0.1.1] - 2026-02-20

### Added
- `@transform_struct` decorator for post-validation struct-level transforms on any `TransformStruct` (including `BaseSettings` and nested structs).
- Support for struct-level hooks with signatures `(instance)` or `(cls, instance)`.

### Changed
- Struct transform pipeline now supports final post-parse mutation plus full revalidation.
- After `transform_struct`, values are revalidated for runtime type compatibility and `Field(...)` constraints.
- `transform_struct` hooks must mutate in place and return `None`; incompatible type changes raise `TransformSettingError` in `struct_after` mode.

## [0.1.0] - 2026-02-20

### Added
- Initial public release of `strictenv`.
- `BaseSettings` loader with typed coercion and validation for env values.
- `.env` file parsing with strict mode and explicit file/format errors.
- Field metadata via `Field(...)`, including aliases, descriptions, and constraints.
- Nested settings support via `msgspec.Struct`, including delimiter-based env mapping.
- Nested depth limit (`max_nested_struct_depth`) with dedicated error handling.
- `TransformStruct` and `@transform` (`before`/`after`) for field transforms.
- `write_env_example(...)` generation with field descriptions as comments.
- CI workflow and automated publish workflow using Trusted Publishing.
