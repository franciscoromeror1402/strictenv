# Changelog

All notable changes to this project will be documented in this file.

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

