from __future__ import annotations

import csv
import io

import pytest

from airports_collector.source import SOURCE_COLUMNS, AirportRecord

BASE_ROW: dict[str, str] = {
    "id": "1",
    "ident": "AAA",
    "type": "large_airport",
    "name": "Test International Airport",
    "latitude_deg": "10.0",
    "longitude_deg": "20.0",
    "elevation_ft": "100",
    "continent": "AS",
    "iso_country": "CN",
    "iso_region": "CN-11",
    "municipality": "Testville",
    "scheduled_service": "yes",
    "gps_code": "AAAA",
    "icao_code": "AAAA",
    "iata_code": "AAA",
    "local_code": "",
    "home_link": "https://example.com",
    "wikipedia_link": "https://en.wikipedia.org/wiki/Test",
    "keywords": "Test, 试验",
}


def make_row(**overrides: str) -> dict[str, str]:
    row = dict(BASE_ROW)
    row.update({key: str(value) for key, value in overrides.items()})
    return row


def to_csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(SOURCE_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def make_record(**overrides: object) -> AirportRecord:
    row = make_row()
    payload: dict[str, object] = {
        "id": int(row["id"]),
        "ident": row["ident"],
        "type": row["type"],
        "name": row["name"],
        "latitude_deg": 10.0,
        "longitude_deg": 20.0,
        "elevation_ft": 100,
        "continent": "AS",
        "iso_country": "CN",
        "iso_region": "CN-11",
        "municipality": "Testville",
        "scheduled_service": "yes",
        "gps_code": "AAAA",
        "icao_code": "AAAA",
        "iata_code": "AAA",
        "local_code": None,
        "home_link": "https://example.com",
        "wikipedia_link": None,
        "keywords": None,
    }
    payload.update(overrides)
    return AirportRecord(**payload)  # type: ignore[arg-type]


@pytest.fixture
def sample_csv() -> str:
    rows = [
        make_row(),
        make_row(id="2", ident="BBB", type="small_airport", name="Small Field", iata_code="", icao_code="BBBB"),
        make_row(id="3", ident="CCC", type="closed", name="Closed Field", iata_code="", icao_code=""),
    ]
    return to_csv(rows)


class FakeStorage:
    """记录 SQL 调用的假存储；responses 以 SQL 片段为键（最长匹配优先）。"""

    def __init__(self, responses: dict[str, list[dict]] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, tuple]] = []

    def _respond(self, sql: str, params) -> list[dict]:
        self.calls.append((sql, tuple(params)))
        for fragment in sorted(self.responses, key=len, reverse=True):
            if fragment in sql:
                value = self.responses[fragment]
                return value() if callable(value) else value
        return []

    def query(self, sql: str, params=()) -> list[dict]:
        return self._respond(sql, params)

    def execute(self, sql: str, params=()) -> list[dict]:
        return self._respond(sql, params)

    def execute_script(self, sql: str) -> list[list[dict]]:
        from airports_collector.storage.clients import split_sql_script

        return [self._respond(statement, ()) for statement in split_sql_script(sql)]

    def transaction(self):
        from contextlib import nullcontext

        return nullcontext(self)

    def close(self) -> None:
        pass

    def sql_calls(self) -> list[str]:
        return [sql for sql, _ in self.calls]

    def params_for(self, fragment: str) -> list[tuple]:
        return [params for sql, params in self.calls if fragment in sql]


class FakeRepository:
    def __init__(self, *, batch_size: int = 10, fail_on_merge: bool = False) -> None:
        from airports_collector.storage.repository import MergeStats

        self.batch_size = batch_size
        self.fail_on_merge = fail_on_merge
        self.started: list[tuple[str, str | None]] = []
        self.staged: list[tuple[int, list[dict]]] = []
        self.deactivated: list[object] = []
        self.finished: list[dict] = []
        self.failed: list[tuple[int, str]] = []
        self.cleared: list[int] = []
        self._merge_stats = MergeStats(inserted=2, updated=1, unchanged=0, reactivated=0, deactivated=0)

    def start_run(self, source_url: str, names_file_sha256: str | None) -> int:
        self.started.append((source_url, names_file_sha256))
        return 7

    def clear_staging(self, run_id: int) -> None:
        self.cleared.append(run_id)

    def stage_rows(self, run_id: int, snapshot_at, rows: list[dict]) -> int:
        self.staged.append((run_id, list(rows)))
        return len(rows)

    def merge(self, run_id: int):
        if self.fail_on_merge:
            raise RuntimeError("boom")
        return self._merge_stats

    def deactivate_missing(self, snapshot_at) -> int:
        self.deactivated.append(snapshot_at)
        return 1

    def finish_run(self, run_id: int, **kwargs) -> None:
        self.finished.append({"run_id": run_id, **kwargs})

    def fail_run(self, run_id: int, message: str) -> None:
        self.failed.append((run_id, message))

    def chunks(self, rows: list[dict]):
        for start in range(0, len(rows), self.batch_size):
            yield rows[start : start + self.batch_size]
