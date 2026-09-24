from __future__ import annotations

from pathlib import Path

import pytest

from airports_collector.config import ConfigError, load_settings


def _write_codex(root: Path, base_url: str = "http://codex.example/", key: str = "ik_codex") -> None:
    config_dir = root / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        f"""
[ mcp_servers.insforge.env ]
API_BASE_URL = "{base_url}"
API_KEY = "{key}"
""".replace("[ mcp_servers", "[mcp_servers"),
        encoding="utf-8",
    )


def test_reads_codex_config(tmp_path: Path) -> None:
    _write_codex(tmp_path)
    settings = load_settings(repo_root=tmp_path, environ={})
    assert settings.api_base_url == "http://codex.example"
    assert settings.api_key == "ik_codex"
    assert settings.migration_dir == tmp_path / "migrations"
    assert settings.names_file == tmp_path / "data" / "airport_names_zh.csv"
    assert settings.batch_size == 1000
    assert settings.database_dsn is None


def test_env_file_overrides_codex_and_env_wins(tmp_path: Path) -> None:
    _write_codex(tmp_path)
    (tmp_path / ".env").write_text(
        "API_KEY=ik_env_file\nAIRPORTS_BATCH_SIZE=50\n", encoding="utf-8"
    )
    settings = load_settings(repo_root=tmp_path, environ={"API_KEY": "ik_process"})
    assert settings.api_key == "ik_process"
    assert settings.batch_size == 50


def test_absolute_paths_kept(tmp_path: Path) -> None:
    _write_codex(tmp_path)
    settings = load_settings(
        repo_root=tmp_path,
        environ={"AIRPORTS_NAMES_FILE": "/tmp/names.csv", "AIRPORTS_BATCH_SIZE": "20"},
    )
    assert settings.names_file == Path("/tmp/names.csv")
    assert settings.batch_size == 20


def test_missing_credentials_only_break_storage(tmp_path: Path) -> None:
    """公开数据命令（names/export-web）不需要凭据，只有写库时才报错。"""
    from airports_collector.storage.clients import open_storage

    settings = load_settings(repo_root=tmp_path, environ={})
    assert settings.api_base_url == "" and settings.api_key == ""
    with pytest.raises(ConfigError, match="API_BASE_URL"):
        open_storage(settings)


def test_redacted_key(tmp_path: Path) -> None:
    _write_codex(tmp_path, key="ik_abcdefghijkl")
    settings = load_settings(repo_root=tmp_path, environ={})
    assert settings.redacted_api_key == "ik_ab***ijkl"
