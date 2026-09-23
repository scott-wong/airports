from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from airports_collector.collector import collect
from airports_collector.zh_names import (
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    NameEntry,
    ZhNamesError,
    write_names,
)
from conftest import FakeRepository


def _entry(
    record_id: int,
    ident: str,
    type_: str,
    iata: str | None,
    icao: str | None,
    name: str,
    name_zh: str,
    municipality: str | None = None,
    municipality_zh: str | None = None,
) -> NameEntry:
    return NameEntry(
        id=record_id,
        ident=ident,
        type=type_,
        iata_code=iata,
        icao_code=icao,
        name=name,
        name_zh=name_zh,
        name_zh_source=f"wikidata:Q{record_id}:zh-cn",
        municipality=municipality,
        municipality_zh=municipality_zh,
        municipality_zh_source=f"wikipedia:en:{municipality}>zh" if municipality_zh else None,
        name_zh_status=STATUS_RESOLVED,
        municipality_zh_status=STATUS_RESOLVED if municipality_zh else STATUS_UNRESOLVED,
    )


def _names_file(tmp_path: Path) -> Path:
    path = tmp_path / "airport_names_zh.csv"
    write_names(
        path,
        [
            _entry(
                1,
                "AAA",
                "large_airport",
                "AAA",
                "AAAA",
                "Test International Airport",
                "测试国际机场",
                "Testville",
                "试验城",
            ),
            _entry(4, "DDD", "medium_airport", "DDD", "DDDD", "Medium Airport", "中型机场"),
        ],
    )
    return path


def test_collect_happy_path(tmp_path: Path, sample_csv: str) -> None:
    csv_path = tmp_path / "airports.csv"
    csv_path.write_text(sample_csv, encoding="utf-8")
    names_path = _names_file(tmp_path)
    repository = FakeRepository(batch_size=2)
    with httpx.Client() as client:
        result = collect(
            repository,
            client,
            source_url="https://example.com/airports.csv",
            names_path=names_path,
            csv_path=csv_path,
            min_rows=1,
            min_large_airports=1,
        )
    assert result.run_id == 7
    assert result.rows_total == 4
    assert result.rows_named_airports == 2
    assert result.rows_missing_zh == 0
    assert repository.started[0][1] is not None
    staged_rows = [row for _, rows in repository.staged for row in rows]
    assert len(staged_rows) == 4
    by_id = {row["id"]: row for row in staged_rows}
    assert by_id[1]["name_zh"] == "测试国际机场"
    assert by_id[1]["municipality_zh"] == "试验城"
    assert by_id[1]["municipality_zh_source"] == "wikipedia:en:Testville>zh"
    assert by_id[4]["name_zh"] == "中型机场"
    assert by_id[2]["name_zh"] is None
    assert len(by_id[1]["row_hash"]) == 64
    assert repository.cleared == [7, 7]
    assert repository.deactivated
    finish = repository.finished[0]
    assert finish["rows_total"] == 4
    assert finish["rows_named_airports"] == 2
    assert finish["rows_inserted"] == 2
    assert not repository.failed


def test_collect_requires_names_file(tmp_path: Path, sample_csv: str) -> None:
    csv_path = tmp_path / "airports.csv"
    csv_path.write_text(sample_csv, encoding="utf-8")
    repository = FakeRepository()
    with httpx.Client() as client, pytest.raises(ZhNamesError):
        collect(
            repository,
            client,
            source_url="https://example.com/airports.csv",
            names_path=tmp_path / "missing.csv",
            csv_path=csv_path,
            min_rows=1,
            min_large_airports=1,
        )
    assert repository.started == []


def test_collect_allow_missing_names(tmp_path: Path, sample_csv: str) -> None:
    csv_path = tmp_path / "airports.csv"
    csv_path.write_text(sample_csv, encoding="utf-8")
    repository = FakeRepository()
    with httpx.Client() as client:
        result = collect(
            repository,
            client,
            source_url="https://example.com/airports.csv",
            names_path=tmp_path / "missing.csv",
            csv_path=csv_path,
            allow_missing_names=True,
            min_rows=1,
            min_large_airports=1,
        )
    assert result.rows_named_airports == 2
    assert result.rows_missing_zh == 2
    assert repository.finished[0]["rows_missing_zh"] == 2


def test_collect_marks_run_failed(tmp_path: Path, sample_csv: str) -> None:
    csv_path = tmp_path / "airports.csv"
    csv_path.write_text(sample_csv, encoding="utf-8")
    repository = FakeRepository(fail_on_merge=True)
    with httpx.Client() as client, pytest.raises(RuntimeError):
        collect(
            repository,
            client,
            source_url="https://example.com/airports.csv",
            names_path=_names_file(tmp_path),
            csv_path=csv_path,
            min_rows=1,
            min_large_airports=1,
        )
    assert repository.failed and repository.failed[0][0] == 7
    assert not repository.finished
