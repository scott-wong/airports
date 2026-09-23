from __future__ import annotations

from pathlib import Path

from airports_collector.storage.migrations import MigrationRunner
from conftest import FakeStorage

MIGRATION_SQL = """
-- 注释行
CREATE SCHEMA IF NOT EXISTS airports;

CREATE TABLE IF NOT EXISTS airports.schema_migrations (version text PRIMARY KEY);
"""


def test_discover_sorted(tmp_path: Path) -> None:
    (tmp_path / "002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    runner = MigrationRunner(FakeStorage(), tmp_path)
    assert [version for version, _ in runner.discover_migrations()] == ["001", "002"]
    assert MigrationRunner(FakeStorage(), tmp_path / "missing").discover_migrations() == []


def test_migrate_records_version(tmp_path: Path) -> None:
    (tmp_path / "001_airports.sql").write_text(MIGRATION_SQL, encoding="utf-8")
    storage = FakeStorage({"information_schema.tables": []})
    runner = MigrationRunner(storage, tmp_path)
    assert runner.migrate() == ["001"]
    assert any("CREATE SCHEMA IF NOT EXISTS airports" in sql for sql in storage.sql_calls())
    inserts = storage.params_for("INSERT INTO airports.schema_migrations")
    assert len(inserts) == 1
    version, filename, checksum = inserts[0]
    assert version == "001"
    assert filename == "001_airports.sql"
    assert len(checksum) == 64


def test_migrate_skips_applied(tmp_path: Path) -> None:
    (tmp_path / "001_airports.sql").write_text("SELECT 1;", encoding="utf-8")
    storage = FakeStorage(
        {
            "FROM information_schema.tables": [{"?column?": 1}],
            "SELECT version FROM airports.schema_migrations": [{"version": "001"}],
        }
    )
    assert MigrationRunner(storage, tmp_path).migrate() == []
    assert not any("INSERT INTO airports.schema_migrations" in sql for sql in storage.sql_calls())


def test_validate_reports_missing() -> None:
    storage = FakeStorage({"information_schema.tables": [], "information_schema.views": [], "information_schema.columns": []})
    problems = MigrationRunner(storage, Path("/nonexistent")).validate()
    assert any("缺少表" in problem for problem in problems)
    assert any("缺少视图" in problem for problem in problems)
    assert any("缺少列" in problem for problem in problems)


def test_validate_ok() -> None:
    from airports_collector.storage.migrations import (
        EXPECTED_AIRPORT_COLUMNS,
        EXPECTED_TABLES,
        EXPECTED_VIEWS,
    )

    storage = FakeStorage(
        {
            "table_type = 'BASE TABLE'": [{"table_name": name} for name in sorted(EXPECTED_TABLES)],
            "FROM information_schema.views": [{"table_name": name} for name in sorted(EXPECTED_VIEWS)],
            "table_name = 'airport'": [{"column_name": name} for name in sorted(EXPECTED_AIRPORT_COLUMNS)],
        }
    )
    assert MigrationRunner(storage, Path("/nonexistent")).validate() == []
