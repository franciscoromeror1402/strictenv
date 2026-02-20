# Contributing to strictenv

Thanks for contributing.

## Before You Start

- Open an issue first for large changes (new features, API changes, behavior changes).
- Keep pull requests focused on one topic.
- Include tests for behavior changes.
- Update docs when public behavior changes.

## Local Setup

```bash
uv sync --dev
```

## Development Checks

Run all checks before opening a PR:

```bash
uv run ruff check .
uv run mypy src
uv run pytest -q
uv build
```

## Branching and Commits

- Create a branch from `main`.
- Use clear commit messages.
- Rebase/sync with `main` when needed to keep conflicts small.

Example:

```bash
git checkout -b feat/my-change
```

## Pull Request Guidelines

Your PR description should include:

- What changed.
- Why it changed.
- Any compatibility notes.
- Any docs/tests added.

PR checklist:

- [ ] Code is formatted/linted.
- [ ] Types pass (`mypy`).
- [ ] Tests pass.
- [ ] Docs updated (if needed).

## Notes on Releases

Package publishing and GitHub releases are maintainer-only tasks.
Contributors should not run `uv publish`.
Maintainers publish via the tag workflow (`vX.Y.Z`).
