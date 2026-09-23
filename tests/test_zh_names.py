from __future__ import annotations

from pathlib import Path

import pytest

from airports_collector.zh_names import (
    Candidate,
    NameEntry,
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    build_entries,
    choose_label,
    distance_km,
    load_names,
    parse_point,
    write_names,
)
from conftest import make_record


def test_parse_point() -> None:
    assert parse_point("Point(116.4 39.9)") == (39.9, 116.4)
    assert parse_point("Point(-0.461941 51.4706)") == (51.4706, -0.461941)
    assert parse_point(None) is None
    assert parse_point("nonsense") is None


def test_distance_bounds() -> None:
    assert distance_km(39.9042, 116.4074, 31.2304, 121.4737) == pytest.approx(1067, rel=0.02)
    assert distance_km(10.0, 20.0, 10.0, 20.0) == 0


def test_choose_label_prefers_simplified() -> None:
    labels = {"zh-hant": {"阿巴坎國際機場"}, "zh-cn": {"阿巴坎国际机场"}, "zh": {"x"}}
    chosen = choose_label(labels)
    assert chosen is not None
    text, suffix, converted = chosen
    assert text == "阿巴坎国际机场"
    assert suffix == "zh-cn"
    assert converted is False


def test_choose_label_converts_traditional() -> None:
    chosen = choose_label({"zh-tw": {"隆城國際機場"}})
    assert chosen is not None
    text, suffix, converted = chosen
    assert text == "隆城国际机场"
    assert suffix == "zh-tw>zh-hans"
    assert converted is True


def test_choose_label_rejects_non_chinese() -> None:
    assert choose_label({"zh": {"London Heathrow Airport"}}) is None
    assert choose_label({"zh": {"LHR"}}) is None


def _candidates(qid: str, coord, labels, code: str = "AAA"):
    candidate = Candidate(qid=qid, coord=coord, labels=labels)
    return {"P238": {code: {qid: candidate}}, "P239": {}}


def test_build_entries_resolves_within_radius() -> None:
    candidates = _candidates("Q1", (10.0, 20.0), {"zh-cn": {"测试国际机场"}})
    entries = build_entries([make_record()], candidates)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name_zh == "测试国际机场"
    assert entry.name_zh_source == "wikidata:Q1:zh-cn"
    assert entry.status == STATUS_RESOLVED


def test_build_entries_rejects_far_candidate() -> None:
    candidates = _candidates("Q1", (40.0, 20.0), {"zh-cn": {"错误机场"}})
    entries = build_entries([make_record()], candidates)
    assert entries[0].status == STATUS_UNRESOLVED
    assert entries[0].name_zh is None


def test_build_entries_marks_ambiguous() -> None:
    first = Candidate("Q1", (10.0, 20.0), {"zh-cn": {"甲机场"}})
    second = Candidate("Q2", (10.0001, 20.0), {"zh-cn": {"乙机场"}})
    candidates = {"P238": {"AAA": {"Q1": first, "Q2": second}}, "P239": {}}
    entries = build_entries([make_record()], candidates)
    assert entries[0].status == STATUS_UNRESOLVED


def test_build_entries_uses_icao_fallback() -> None:
    candidate = Candidate("Q9", (10.0, 20.0), {"zh-hans": {"伊卡奥机场"}})
    candidates = {"P238": {}, "P239": {"AAAA": {"Q9": candidate}}}
    entries = build_entries([make_record(iata_code=None)], candidates)
    assert entries[0].name_zh == "伊卡奥机场"
    assert entries[0].status == STATUS_RESOLVED


def test_build_entries_skips_non_large() -> None:
    entries = build_entries([make_record(type="small_airport")], {"P238": {}, "P239": {}})
    assert entries == []


def test_names_file_round_trip(tmp_path: Path) -> None:
    entry = NameEntry(
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
    empty = NameEntry(2, "BBB", None, None, "No Name", None, None, None, None, None, STATUS_UNRESOLVED)
    path = tmp_path / "names.csv"
    digest = write_names(path, [entry, empty])
    assert len(digest) == 64
    loaded = load_names(path)
    assert loaded[1] == entry
    assert loaded[2].name_zh is None
    assert loaded[2].status == STATUS_UNRESOLVED
    assert list(loaded) == [1, 2]


def test_queries_bind_language() -> None:
    from airports_collector.zh_names import _property_query

    labels_query = _property_query("P238", ["AAA"])
    assert "BIND(LANG(?label) AS ?lang)" in labels_query
    assert "wdt:P31/wdt:P279* wd:Q1248784" in labels_query
    assert "wdt:P238" in labels_query


def test_choose_label_rejects_mixed_latin() -> None:
    assert choose_label({"zh": {"Akanu Ibiam國際機場"}}) is None
    assert choose_label({"zh": {"约旦安曼阿丽亚机场"}}) is not None


def test_choose_label_converts_plain_zh_traditional() -> None:
    chosen = choose_label({"zh": {"洛杉磯國際機場"}})
    assert chosen is not None
    text, suffix, converted = chosen
    assert text == "洛杉矶国际机场"
    assert suffix == "zh>zh-hans"
    assert converted is True
