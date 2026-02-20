from __future__ import annotations

from strictenv import BaseSettings


class BasicSettings(BaseSettings):
    debug: bool
    retries: int = 3


def test_load_required_and_defaults() -> None:
    loaded = BasicSettings.load(env={"DEBUG": "true"})
    assert loaded.debug is True
    assert loaded.retries == 3


def test_source_precedence(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEBUG=false\nRETRIES=11\n", encoding="utf-8")

    class FileSettings(BaseSettings):
        debug: bool
        retries: int = 5

        model_config = {
            "env_file": str(env_file),
        }

    loaded = FileSettings.load(
        env={"DEBUG": "true", "RETRIES": "7"},
        overrides={"retries": 99},
    )
    assert loaded.debug is True
    assert loaded.retries == 99
