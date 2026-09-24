from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SOURCE_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
DEFAULT_NAMES_FILE = "data/airport_names_zh.csv"
DEFAULT_LLM_SUPPLEMENT_FILE = "data/airport_names_llm.csv"
DEFAULT_WEB_EXPORT_DIR = "web/globe/public"
DEFAULT_MIGRATION_DIR = "migrations"
DEFAULT_BATCH_SIZE = 1000

# 与 flight-data 共用的键名，便于两个项目读同一份 .codex/config.toml。
SHARED_KEYS = ("API_BASE_URL", "API_KEY")
PROJECT_KEYS = (
    "AIRPORTS_SOURCE_URL",
    "AIRPORTS_MIGRATION_DIR",
    "AIRPORTS_NAMES_FILE",
    "AIRPORTS_LLM_SUPPLEMENT_FILE",
    "AIRPORTS_WEB_EXPORT_DIR",
    "AIRPORTS_BATCH_SIZE",
    "AIRPORTS_DATABASE_DSN",
)


class ConfigError(RuntimeError):
    """配置缺失或不合法。"""


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    api_key: str
    source_url: str
    migration_dir: Path
    names_file: Path
    llm_supplement_file: Path
    web_export_dir: Path
    batch_size: int
    database_dsn: str | None
    repo_root: Path

    @property
    def redacted_api_key(self) -> str:
        if len(self.api_key) <= 8:
            return "***"
        return f"{self.api_key[:5]}***{self.api_key[-4:]}"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _parse_codex_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:  # pragma: no cover - 配置损坏时给出清晰错误
        raise ConfigError(f"无法解析 {path}: {error}") from error
    env = payload.get("mcp_servers", {}).get("insforge", {}).get("env", {})
    if not isinstance(env, dict):
        return {}
    return {str(key): str(value) for key, value in env.items() if value is not None}


def load_settings(
    repo_root: Path | str | None = None,
    env_file: Path | str | None = None,
    environ: dict[str, str] | None = None,
) -> Settings:
    """优先级：显式环境变量 > .env > .codex/config.toml > 默认值。"""
    root = Path(repo_root).resolve() if repo_root is not None else Path.cwd().resolve()
    env_path = Path(env_file) if env_file is not None else root / ".env"
    if not env_path.is_absolute():
        env_path = root / env_path
    environ = dict(os.environ if environ is None else environ)

    merged: dict[str, str] = {}
    merged.update(_parse_codex_config(root / ".codex" / "config.toml"))
    merged.update(_parse_env_file(env_path))
    for key in SHARED_KEYS + PROJECT_KEYS:
        value = environ.get(key)
        if value:
            merged[key] = value

    # 凭据允许为空：names/export-web 这类只处理公开数据的命令不需要数据库。
    # 真正要写库时由 open_storage() 校验（见 storage/clients.py）。
    api_base_url = (merged.get("API_BASE_URL") or "").strip().rstrip("/")
    api_key = (merged.get("API_KEY") or "").strip()

    try:
        batch_size = int(merged.get("AIRPORTS_BATCH_SIZE") or DEFAULT_BATCH_SIZE)
    except ValueError as error:
        raise ConfigError("AIRPORTS_BATCH_SIZE 必须是整数") from error
    if batch_size <= 0:
        raise ConfigError("AIRPORTS_BATCH_SIZE 必须大于 0")

    def _path(key: str, default: str) -> Path:
        raw = (merged.get(key) or default).strip()
        candidate = Path(raw)
        return candidate if candidate.is_absolute() else root / candidate

    database_dsn = (merged.get("AIRPORTS_DATABASE_DSN") or "").strip() or None

    return Settings(
        api_base_url=api_base_url,
        api_key=api_key,
        source_url=(merged.get("AIRPORTS_SOURCE_URL") or DEFAULT_SOURCE_URL).strip(),
        migration_dir=_path("AIRPORTS_MIGRATION_DIR", DEFAULT_MIGRATION_DIR),
        names_file=_path("AIRPORTS_NAMES_FILE", DEFAULT_NAMES_FILE),
        llm_supplement_file=_path(
            "AIRPORTS_LLM_SUPPLEMENT_FILE", DEFAULT_LLM_SUPPLEMENT_FILE
        ),
        web_export_dir=_path("AIRPORTS_WEB_EXPORT_DIR", DEFAULT_WEB_EXPORT_DIR),
        batch_size=batch_size,
        database_dsn=database_dsn,
        repo_root=root,
    )
