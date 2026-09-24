from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from airports_collector.web_export import (
    SNAPSHOT_FIELDS,
    build_snapshot,
    export_web,
    summarize,
    write_export,
)
from airports_collector.zh_names import STATUS_RESOLVED, NameEntry, write_names
from conftest import make_record


def _entry(**overrides) -> NameEntry:
    payload = dict(
        id=1,
        ident="AAA",
        type="large_airport",
        iata_code="AAA",
        icao_code="AAAA",
        name="Test International Airport",
        name_zh="测试国际机场",
        name_zh_source="wikidata:Q1:zh-cn",
        municipality="Testville",
        municipality_zh="试验城",
        municipality_zh_source="wikipedia:en:Testville>zh",
        name_zh_status=STATUS_RESOLVED,
        location_zh="测试镇",
        location_zh_source="wikidata:Q1:P131:Q9:zh-cn",
    )
    payload.update(overrides)
    return NameEntry(**payload)


def test_build_snapshot_shape() -> None:
    records = [
        make_record(id=2, ident="BBB", type="small_airport", name="Small Field"),
        make_record(),
    ]
    snapshot = build_snapshot(
        records,
        {1: _entry()},
        source_url="https://example.com/airports.csv",
        source_sha256="abc",
        names_file="data/airport_names_zh.csv",
        names_sha256="def",
        generated_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    assert snapshot["schemaVersion"] == 1
    assert snapshot["fields"] == list(SNAPSHOT_FIELDS)
    assert [row[0] for row in snapshot["rows"]] == [1, 2]  # 按 id 排序
    index = {name: position for position, name in enumerate(SNAPSHOT_FIELDS)}
    large = snapshot["rows"][0]
    assert large[index["name_zh"]] == "测试国际机场"
    assert large[index["name_zh_source"]] == "wikidata:Q1:zh-cn"
    assert large[index["location_zh"]] == "测试镇"
    assert large[index["latitude_deg"]] == 10.0
    small = snapshot["rows"][1]
    assert small[index["name_zh"]] is None
    assert small[index["type"]] == "small_airport"


def test_summarize_counts() -> None:
    records = [
        make_record(),
        make_record(id=2, ident="BBB", type="medium_airport", name="No Name Airport"),
        make_record(id=3, ident="CCC", type="heliport", name="Pad"),
    ]
    stats = summarize(records, {1: _entry()})
    assert stats["typeCounts"] == {"heliport": 1, "large_airport": 1, "medium_airport": 1}
    assert stats["namedRows"] == 1
    assert stats["unresolvedTargets"] == 1  # medium 没名字，heliport 不算目标


def test_write_export_round_trip(tmp_path: Path) -> None:
    snapshot = {
        "schemaVersion": 1,
        "fields": ["id", "name"],
        "rows": [[index, f"Airport number {index} with a longer name"] for index in range(200)],
    }
    path, manifest_path, raw_bytes, stored_bytes, digest = write_export(snapshot, tmp_path)
    assert path.name == "airports.json.gz"
    assert stored_bytes < raw_bytes
    assert len(digest) == 64
    loaded = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    assert loaded == snapshot
    assert manifest_path.exists() is False  # manifest 由 export_web 写


def test_export_web_end_to_end(tmp_path: Path) -> None:
    names_dir = tmp_path / "data"
    names_dir.mkdir()
    names_path = names_dir / "airport_names_zh.csv"
    write_names(names_path, [_entry()])
    out_dir = tmp_path / "public"
    result = export_web(
        [make_record(), make_record(id=4, ident="DDD", type="medium_airport", name="Other")],
        {1: _entry()},
        out_dir,
        source_url="https://example.com/airports.csv",
        source_sha256="abc123",
        names_file=names_path,
    )
    assert result.rows == 2
    assert result.named_rows == 1
    assert result.unresolved_targets == 1
    assert result.snapshot_path.exists() and result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == 1
    assert manifest["rows"] == 2
    assert manifest["source"]["sha256"] == "abc123"
    assert manifest["names"]["rowCount"] == 1
    assert manifest["snapshot"]["compressed"] is True
    assert manifest["fields"] == list(SNAPSHOT_FIELDS)
