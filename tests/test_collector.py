from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from airports_collector.collector import collect
from airports_collector.zh_names import NameEntry, STATUS_RESOLVED, ZhNamesError, write_names
from conftest import FakeRepository


def _names_file(tmp_path: Path) -> Path:
    path = tmp_path / "airport_names_zh.csv"
    write_names(
        path,
        [
            NameEntry(
                id=1,
                ident="AAA",
                iata_code="AAA",
                icao_code="AAAA",
                name="Test International Airport",
                name_zh="测试国际机场",
                name_zh_source="wikidata:Q1:zh-cn",
                municipality="Testville",
                municipality_zh="试验城",
                municipality_zh_source="wikidata:Q1:P131:zh-cn",
                status=STATUS_RESOLVED,
            )
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
    assert result.rows_total == 3
    assert result.rows_large_airport == 1
    assert result.rows_large_airport_missing_zh == 0
    assert repository.started[0][1] is not None
    staged_rows = [row for _, rows in repository.staged for row in rows]
    assert len(staged_rows) == 3
    by_id = {row["id"]: row for row in staged_rows}
    assert by_id[1]["name_zh"] == "测试国际机场"
    assert by_id[2]["name_zh"] is None
    assert len(by_id[1]["row_hash"]) == 64
    assert repository.cleared == [7, 7]
    assert repository.deactivated
    finish = repository.finished[0]
    assert finish["rows_total"] == 3
    assert finish["rows_large_airport"] == 1
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
    assert result.rows_large_airport_missing_zh == 1
    assert repository.finished[0]["rows_large_airport_missing_zh"] == 1


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
