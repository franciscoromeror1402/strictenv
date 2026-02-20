from __future__ import annotations

from pathlib import Path

import pytest

from strictenv import BaseSettings, EnvFileFormatError


class EnvFeatureSettings(BaseSettings):
    host: str
    port: int
    url: str
    name: str
    plain: str
    empty: str
    multi: str
    escaped: str


def test_env_file_parses_export_comments_quotes_multiline_and_expansion(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "export HOST=localhost",
                "PORT=5432",
                'URL="http://${HOST}:${PORT}" # this comment should be ignored',
                "NAME='acme # not a comment'",
                "PLAIN=value # inline comment",
                "EMPTY=",
                'MULTI="line1',
                'line2"',
                'ESCAPED="line\\nnext\\tindent\\\"quote\\\""',
            ]
        ),
        encoding="utf-8",
    )

    class FileSettings(EnvFeatureSettings):
        model_config = {"env_file": str(env_file)}

    loaded = FileSettings.load(env={})
    assert loaded.host == "localhost"
    assert loaded.port == 5432
    assert loaded.url == "http://localhost:5432"
    assert loaded.name == "acme # not a comment"
    assert loaded.plain == "value"
    assert loaded.empty == ""
    assert loaded.multi == "line1\nline2"
    assert loaded.escaped == 'line\nnext\tindent"quote"'


def test_strict_env_file_rejects_undefined_variable_reference(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("URL=${STRICTENV_MISSING_VAR_9A8B7C}\n", encoding="utf-8")

    class UndefinedVariableSettings(BaseSettings):
        url: str
        model_config = {"env_file": str(env_file)}

    with pytest.raises(EnvFileFormatError) as exc_info:
        UndefinedVariableSettings.load(env={})

    err = exc_info.value
    assert err.line_number == 1
    assert "undefined variable reference" in err.reason


def test_strict_env_file_rejects_cyclic_variable_reference(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=${B}\nB=${A}\n", encoding="utf-8")

    class CyclicVariableSettings(BaseSettings):
        a: str
        b: str
        model_config = {"env_file": str(env_file)}

    with pytest.raises(EnvFileFormatError) as exc_info:
        CyclicVariableSettings.load(env={})

    err = exc_info.value
    assert "cyclic variable reference" in err.reason


def test_non_strict_env_file_uses_empty_string_for_unknown_variable(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("URL=prefix-${STRICTENV_MISSING_VAR_9A8B7C}\n", encoding="utf-8")

    class NonStrictUnknownVariableSettings(BaseSettings):
        url: str
        model_config = {
            "env_file": str(env_file),
            "strict_env_file": False,
        }

    loaded = NonStrictUnknownVariableSettings.load(env={})
    assert loaded.url == "prefix-"
