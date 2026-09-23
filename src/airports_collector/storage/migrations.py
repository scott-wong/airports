from __future__ import annotations

import hashlib
from pathlib import Path

from .clients import StorageClient, StorageUnavailable, split_sql_script

SCHEMA = "airports"
EXPECTED_TABLES = {"airport", "airport_staging", "collector_run", "schema_migrations"}
EXPECTED_VIEWS = {"airport_active"}
EXPECTED_AIRPORT_COLUMNS = {
    "name_zh",
    "municipality_zh",
    "name_zh_source",
    "name_zh_updated_at",
    "row_hash",
    "is_active",
    "deactivated_at",
    "source_snapshot_at",
}


class MigrationError(RuntimeError):
    """迁移无法执行或 schema 不符合预期。"""


class MigrationRunner:
    def __init__(self, storage: StorageClient, migration_dir: Path) -> None:
        self.storage = storage
        self.migration_dir = migration_dir

    def discover_migrations(self) -> list[tuple[str, Path]]:
        if not self.migration_dir.exists():
            return []
        files: list[tuple[str, Path]] = []
        for path in sorted(self.migration_dir.glob("*.sql")):
            version = path.stem.split("_", 1)[0]
            files.append((version, path))
        return sorted(files)

    def applied_versions(self) -> set[str]:
        exists = self.storage.query(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = 'schema_migrations'
            LIMIT 1
            """,
            (SCHEMA,),
        )
        if not exists:
            return set()
        rows = self.storage.query(f"SELECT version FROM {SCHEMA}.schema_migrations ORDER BY version")
        return {str(row["version"]) for row in rows}

    def migrate(self) -> list[str]:
        applied = self.applied_versions()
        newly_applied: list[str] = []
        for version, path in self.discover_migrations():
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            try:
                for statement in split_sql_script(sql):
                    self.storage.execute(statement, ())
            except StorageUnavailable as error:
                raise MigrationError(f"执行 {path.name} 失败: {error}") from error
            self.storage.execute(
                f"""
                INSERT INTO {SCHEMA}.schema_migrations (version, filename, checksum)
                VALUES ($1, $2, $3)
                ON CONFLICT (version) DO NOTHING
                """,
                (version, path.name, self.checksum(path)),
            )
            newly_applied.append(version)
        return newly_applied

    def validate(self) -> list[str]:
        """返回问题清单；空列表表示 schema 符合预期。"""
        problems: list[str] = []
        tables = {
            str(row["table_name"])
            for row in self.storage.query(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = $1 AND table_type = 'BASE TABLE'
                """,
                (SCHEMA,),
            )
        }
        views = {
            str(row["table_name"])
            for row in self.storage.query(
                """
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema = $1
                """,
                (SCHEMA,),
            )
        }
        missing_tables = sorted(EXPECTED_TABLES - tables)
        if missing_tables:
            problems.append(f"缺少表: {missing_tables}")
        missing_views = sorted(EXPECTED_VIEWS - views)
        if missing_views:
            problems.append(f"缺少视图: {missing_views}")

        columns = {
            str(row["column_name"])
            for row in self.storage.query(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = 'airport'
                """,
                (SCHEMA,),
            )
        }
        missing_columns = sorted(EXPECTED_AIRPORT_COLUMNS - columns)
        if missing_columns:
            problems.append(f"airports.airport 缺少列: {missing_columns}")
        return problems

    @staticmethod
    def checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
