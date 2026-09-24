from __future__ import annotations

import base64
import json
import re
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Iterator, Protocol

import httpx

from ..config import ConfigError


class StorageUnavailable(RuntimeError):
    """无法与 InsForge 存储通信。"""


class StorageClient(Protocol):
    def query(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        ...

    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        ...

    def execute_script(self, sql: str) -> list[list[dict[str, Any]]]:
        ...

    def transaction(self) -> Any:
        ...

    def close(self) -> None:
        ...


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def encode_param(value: Any) -> Any:
    """把 Python 值编码成 InsForge rawsql 端点能接受的 JSON 标量。"""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return value.value
    return value


@dataclass
class InsForgeRestClient:
    """InsForge Admin REST 客户端：/api/database/advance/rawsql 可执行任意 SQL（含 DDL）。"""

    base_url: str
    api_key: str
    http_client: httpx.Client | None = None
    timeout: float = 120.0
    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if self.http_client is None:
            self.http_client = httpx.Client(timeout=self.timeout)
            self._owns_client = True

    def _post_sql(self, sql: str, params: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
        assert self.http_client is not None
        try:
            response = self.http_client.post(
                f"{self.base_url}/api/database/advance/rawsql",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": sql, "params": [encode_param(value) for value in params]},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:400] if error.response is not None else ""
            raise StorageUnavailable(f"InsForge 返回 HTTP {error.response.status_code}: {detail}") from error
        except httpx.HTTPError as error:
            raise StorageUnavailable(f"InsForge 请求失败: {error}") from error
        try:
            payload = response.json()
        except ValueError as error:
            raise StorageUnavailable("InsForge 返回了非 JSON 响应") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise StorageUnavailable(f"InsForge 响应缺少 rows 字段: {str(payload)[:200]}")
        return payload["rows"]

    def query(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return self._post_sql(sql, params)

    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return self._post_sql(sql, params)

    def execute_script(self, sql: str) -> list[list[dict[str, Any]]]:
        return [self._post_sql(statement, ()) for statement in split_sql_script(sql)]

    def transaction(self) -> Any:
        # rawsql 端点每次调用即一个事务，无法跨调用开启事务；迁移与合并本身都是单语句安全的。
        return nullcontext(self)

    def close(self) -> None:
        if self._owns_client and self.http_client is not None:
            self.http_client.close()


PLACEHOLDER_RE = re.compile(r"\$(\d+)")


class PostgresClient:
    """直连 PostgreSQL 的回退通道，只在配置了 AIRPORTS_DATABASE_DSN 时启用。"""

    def __init__(self, dsn: str, connect_fn: Callable[[str], Any] | None = None) -> None:
        self.dsn = dsn
        self._connect_fn = connect_fn or _default_connect
        self._connection: Any | None = None

    @staticmethod
    def _convert_placeholders(sql: str) -> tuple[str, list[int]]:
        indices = [int(match.group(1)) - 1 for match in PLACEHOLDER_RE.finditer(sql)]
        return PLACEHOLDER_RE.sub("%s", sql), indices

    @staticmethod
    def _order_params(params: list[Any] | tuple[Any, ...], indices: list[int]) -> list[Any]:
        values = list(params)
        if not indices:
            return values
        return [values[index] for index in indices]

    def _cursor(self) -> Any:
        if self._connection is None or getattr(self._connection, "closed", False):
            self._connection = self._connect_fn(self.dsn)
        return self._connection.cursor()

    def query(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        converted, indices = self._convert_placeholders(sql)
        ordered = self._order_params(params, indices)
        with self._cursor() as cursor:
            cursor.execute(converted, ordered or None)
            if cursor.description is None:
                return []
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        rows = self.query(sql, params)
        if self._connection is not None:
            self._connection.commit()
        return rows

    def execute_script(self, sql: str) -> list[list[dict[str, Any]]]:
        return [self.execute(statement) for statement in split_sql_script(sql)]

    @contextmanager
    def transaction(self) -> Iterator["PostgresClient"]:
        self._cursor()
        try:
            yield self
            if self._connection is not None:
                self._connection.commit()
        except Exception:
            if self._connection is not None:
                self._connection.rollback()
            raise

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _default_connect(dsn: str) -> Any:  # pragma: no cover - 需要真实数据库
    import psycopg2

    return psycopg2.connect(dsn)


def open_storage(settings: Any, *, on_progress: Any | None = None) -> StorageClient:
    """默认走 InsForge Admin REST；配置了 DSN 且 REST 不可用时回退直连 PostgreSQL。"""
    if not getattr(settings, "api_base_url", "") or not getattr(settings, "api_key", ""):
        raise ConfigError("缺少 API_BASE_URL / API_KEY：写库命令需要 InsForge 凭据（.codex/config.toml、.env 或环境变量）")
    rest = InsForgeRestClient(settings.api_base_url, settings.api_key)
    try:
        rest.query("SELECT 1 AS ok")
        return rest
    except StorageUnavailable as error:
        rest.close()
        if not getattr(settings, "database_dsn", None):
            raise
        if on_progress:
            on_progress(f"InsForge Admin REST 不可用（{error}），回退直连数据库")
        postgres = PostgresClient(str(settings.database_dsn))
        postgres.query("SELECT 1 AS ok")
        return postgres


def split_sql_script(sql: str) -> list[str]:
    """按行拆分 SQL 脚本；行首 -- 注释丢弃，语句以行尾 ; 结束。"""
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            buffer.clear()
    if buffer:
        statement = "\n".join(buffer).strip().rstrip(";").strip()
        if statement:
            statements.append(statement)
    return statements
