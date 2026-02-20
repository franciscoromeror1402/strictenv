from __future__ import annotations

import os
import re
from typing import Mapping

from .errors import (
    EnvFileFormatError,
    EnvFileNotFoundError,
    EnvFileReadError,
    EnvKeyConflictError,
)

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENV_EXPANSION_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def format_env_key(prefix: str, field_name: str, case_sensitive: bool) -> str:
    """
    Compose the environment key for a field using prefix and case policy.

    Arguments:
        prefix (str): Optional settings prefix to prepend.
        field_name (str): Declared field name or alias.
        case_sensitive (bool): Whether key casing must be preserved.

    Returns:
        The normalized environment key used for lookups.
    """
    key = f"{prefix}{field_name}"
    return key if case_sensitive else key.upper()


def build_env_map(
    env: Mapping[str, str] | None,
    env_file: str | None,
    case_sensitive: bool,
    *,
    strict_env_file: bool = True,
) -> dict[str, str]:
    """
    Build the effective environment mapping used by the settings loader.

    Arguments:
        env (Mapping[str, str] | None): Optional explicit environment mapping.
        env_file (str | None): Optional path to a `.env`-style file.
        case_sensitive (bool): Whether keys should keep original casing.
        strict_env_file (bool): Whether env-file read/parse failures should raise.

    Returns:
        A merged mapping from file values and runtime environment values.

    Raises:
        EnvFileNotFoundError: If `env_file` is configured but does not exist.
        EnvFileReadError: If `env_file` cannot be read.
        EnvFileFormatError: If an env file line is malformed in strict mode.
        EnvKeyConflictError: If keys collide when `case_sensitive=False` in strict mode.
    """
    merged: dict[str, str] = {}
    if env_file:
        merged.update(parse_env_file(env_file, strict=strict_env_file))
    merged.update(env or os.environ)
    if case_sensitive:
        return dict(merged)
    if not strict_env_file:
        return {key.upper(): value for key, value in merged.items()}

    normalized: dict[str, str] = {}
    seen_original: dict[str, str] = {}
    for key, value in merged.items():
        normalized_key = key.upper()
        previous_key = seen_original.get(normalized_key)
        if previous_key is not None and previous_key != key:
            raise EnvKeyConflictError(
                normalized_key=normalized_key,
                first_key=previous_key,
                second_key=key,
            )
        seen_original[normalized_key] = key
        normalized[normalized_key] = value
    return normalized


def parse_env_file(path: str, *, strict: bool = True) -> dict[str, str]:
    """
    Parse a `.env` file into key/value pairs.

    Args:
        path: File path to read.
        strict: Whether invalid file/format conditions should raise exceptions.

    Returns:
        Parsed key/value pairs.

    Raises:
        EnvFileNotFoundError: If the file does not exist in strict mode.
        EnvFileReadError: If the file exists but cannot be read in strict mode.
        EnvFileFormatError: If non-comment lines are malformed in strict mode.
    """
    data: dict[str, str] = {}
    line_numbers: dict[str, int] = {}
    lines = _read_env_lines(path, strict=strict)
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line_number = index + 1
        stripped = raw_line.strip()

        if not stripped or stripped.startswith("#"):
            index += 1
            continue

        entry = stripped
        if entry.startswith("export "):
            entry = entry[len("export ") :].lstrip()

        if "=" not in entry:
            if strict:
                raise EnvFileFormatError(
                    env_file=path,
                    line_number=line_number,
                    line=stripped,
                    reason="missing '=' delimiter",
                )
            index += 1
            continue

        raw_key, raw_value = entry.split("=", 1)
        key = raw_key.strip()
        if not key:
            if strict:
                raise EnvFileFormatError(
                    env_file=path,
                    line_number=line_number,
                    line=stripped,
                    reason="empty key",
                )
            index += 1
            continue
        if _ENV_KEY_RE.fullmatch(key) is None:
            if strict:
                raise EnvFileFormatError(
                    env_file=path,
                    line_number=line_number,
                    line=stripped,
                    reason="invalid variable name",
                )
            index += 1
            continue
        if strict and key in data:
            raise EnvFileFormatError(
                env_file=path,
                line_number=line_number,
                line=stripped,
                reason=f"duplicate key: {key}",
            )

        value, next_index = _parse_env_value(
            lines=lines,
            start_index=index,
            raw_value=raw_value,
            env_file=path,
            strict=strict,
        )
        data[key] = value
        line_numbers[key] = line_number
        index = next_index

    _expand_env_variables(
        values=data,
        line_numbers=line_numbers,
        env_file=path,
        strict=strict,
    )
    return data

def _read_env_lines(path: str, *, strict: bool) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read().splitlines()
    except FileNotFoundError:
        if strict:
            raise EnvFileNotFoundError(env_file=path) from None
        return []
    except UnicodeDecodeError as exc:
        if strict:
            raise EnvFileReadError(
                env_file=path,
                reason="invalid UTF-8 encoding",
            ) from exc
        return []
    except OSError as exc:
        if strict:
            raise EnvFileReadError(env_file=path, reason=str(exc)) from exc
        return []


def _parse_env_value(
    *,
    lines: list[str],
    start_index: int,
    raw_value: str,
    env_file: str,
    strict: bool,
) -> tuple[str, int]:
    value = raw_value.lstrip()
    if not value:
        return "", start_index + 1

    if value[0] in {'"', "'"}:
        return _parse_quoted_value(
            lines=lines,
            start_index=start_index,
            initial=value,
            env_file=env_file,
            strict=strict,
        )

    return _strip_inline_comment(value), start_index + 1


def _parse_quoted_value(
    *,
    lines: list[str],
    start_index: int,
    initial: str,
    env_file: str,
    strict: bool,
) -> tuple[str, int]:
    quote = initial[0]
    buffer = initial
    index = start_index

    while True:
        closing_index = _find_unescaped_quote(buffer, quote, start=1)
        if closing_index != -1:
            inner = buffer[1:closing_index]
            trailing = buffer[closing_index + 1 :].strip()
            if trailing and not trailing.startswith("#") and strict:
                raise EnvFileFormatError(
                    env_file=env_file,
                    line_number=start_index + 1,
                    line=buffer,
                    reason="unexpected characters after closing quote",
                )
            return _unescape_quoted(inner, quote), index + 1

        index += 1
        if index >= len(lines):
            if strict:
                raise EnvFileFormatError(
                    env_file=env_file,
                    line_number=start_index + 1,
                    line=initial,
                    reason="unterminated quoted value",
                )
            return _unescape_quoted(buffer[1:], quote), len(lines)
        buffer = f"{buffer}\n{lines[index]}"


def _find_unescaped_quote(text: str, quote: str, *, start: int) -> int:
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return index
    return -1


def _strip_inline_comment(value: str) -> str:
    for index, char in enumerate(value):
        if char != "#":
            continue
        if index > 0 and value[index - 1] == "\\":
            continue
        if index == 0 or value[index - 1].isspace():
            return value[:index].rstrip()
    return value.strip()


def _unescape_quoted(value: str, quote: str) -> str:
    if quote == "'":
        escape_map = {"\\": "\\", "'": "'"}
    else:
        escape_map = {
            "\\": "\\",
            '"': '"',
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "$": "$",
        }

    parsed: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            parsed.append(char)
            index += 1
            continue
        if index + 1 >= len(value):
            parsed.append("\\")
            index += 1
            continue
        next_char = value[index + 1]
        parsed.append(escape_map.get(next_char, next_char))
        index += 2
    return "".join(parsed)


def _expand_env_variables(
    *,
    values: dict[str, str],
    line_numbers: dict[str, int],
    env_file: str,
    strict: bool,
) -> None:
    resolved: dict[str, str] = {}
    stack: list[str] = []

    def resolve(key: str) -> str:
        if key in resolved:
            return resolved[key]
        if key in stack:
            if strict:
                chain = " -> ".join([*stack, key])
                raise EnvFileFormatError(
                    env_file=env_file,
                    line_number=line_numbers.get(key, 0),
                    line=values.get(key, ""),
                    reason=f"cyclic variable reference: {chain}",
                )
            return values.get(key, "")

        stack.append(key)
        try:
            raw_value = values.get(key, "")

            def replace(match: re.Match[str]) -> str:
                ref = match.group(1)
                if ref in values:
                    return resolve(ref)
                env_value = os.environ.get(ref)
                if env_value is not None:
                    return env_value
                if strict:
                    raise EnvFileFormatError(
                        env_file=env_file,
                        line_number=line_numbers.get(key, 0),
                        line=raw_value,
                        reason=f"undefined variable reference: {ref}",
                    )
                return ""

            expanded = _ENV_EXPANSION_RE.sub(replace, raw_value)
            resolved[key] = expanded
            return expanded
        finally:
            stack.pop()

    for key in list(values):
        values[key] = resolve(key)
