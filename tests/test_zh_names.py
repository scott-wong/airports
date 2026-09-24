from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from airports_collector import zh_names
from airports_collector.zh_names import (
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    AdminCandidate,
    Candidate,
    NameEntry,
    build_entries,
    choose_label,
    clean_wiki_title,
    distance_km,
    fetch_admin_labels,
    fetch_wikipedia_city_names,
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
    chosen = choose_label({"zh-hant": {"阿巴坎國際機場"}, "zh-cn": {"阿巴坎国际机场"}})
    assert chosen is not None
    text, suffix, converted = chosen
    assert (text, suffix, converted) == ("阿巴坎国际机场", "zh-cn", False)


def test_choose_label_converts_traditional() -> None:
    chosen = choose_label({"zh-tw": {"隆城國際機場"}})
    assert chosen is not None
    text, suffix, converted = chosen
    assert text == "隆城国际机场"
    assert suffix == "zh-tw>zh-hans"
    assert converted is True


def test_choose_label_converts_plain_zh_traditional() -> None:
    chosen = choose_label({"zh": {"洛杉磯國際機場"}})
    assert chosen is not None
    text, suffix, converted = chosen
    assert text == "洛杉矶国际机场"
    assert suffix == "zh>zh-hans"
    assert converted is True


def test_choose_label_rejects_garbage() -> None:
    assert choose_label({"zh": {"London Heathrow Airport"}}) is None
    assert choose_label({"zh": {"Akanu Ibiam國際機場"}}) is None
    assert choose_label({"zh": {"LHR"}}) is None


def test_clean_wiki_title() -> None:
    assert clean_wiki_title("贝克斯菲尔德 (加利福尼亚州)") == "贝克斯菲尔德"
    assert clean_wiki_title("阿什維爾 (北卡羅萊納州)") == "阿什维尔"
    assert clean_wiki_title("ABC City") is None


def _candidates(qid: str, coord, labels, code: str = "AAA"):
    candidate = Candidate(qid=qid, coord=coord, labels=labels)
    return {"P238": {code: {qid: candidate}}, "P239": {}}


def test_build_entries_resolves_large_and_medium() -> None:
    candidates = _candidates("Q1", (10.0, 20.0), {"zh-cn": {"测试国际机场"}})
    entries = build_entries(
        [make_record(), make_record(id=2, ident="BBB", type="medium_airport")], candidates
    )
    assert [entry.type for entry in entries] == ["large_airport", "medium_airport"]
    assert all(entry.name_zh == "测试国际机场" for entry in entries)
    assert entries[0].name_zh_source == "wikidata:Q1:zh-cn"
    assert entries[0].name_zh_status == STATUS_RESOLVED


def test_build_entries_skips_other_types() -> None:
    assert build_entries([make_record(type="small_airport")], {"P238": {}, "P239": {}}) == []
    assert build_entries([make_record(type="closed")], {"P238": {}, "P239": {}}) == []


def test_build_entries_rejects_far_candidate() -> None:
    candidates = _candidates("Q1", (40.0, 20.0), {"zh-cn": {"错误机场"}})
    entries = build_entries([make_record()], candidates)
    assert entries[0].name_zh_status == STATUS_UNRESOLVED
    assert entries[0].name_zh is None


def test_build_entries_marks_ambiguous() -> None:
    first = Candidate("Q1", (10.0, 20.0), {"zh-cn": {"甲机场"}})
    second = Candidate("Q2", (10.0001, 20.0), {"zh-cn": {"乙机场"}})
    candidates = {"P238": {"AAA": {"Q1": first, "Q2": second}}, "P239": {}}
    entries = build_entries([make_record()], candidates)
    assert entries[0].name_zh_status == STATUS_UNRESOLVED


def test_build_entries_uses_icao_fallback() -> None:
    candidate = Candidate("Q9", (10.0, 20.0), {"zh-hans": {"伊卡奥机场"}})
    candidates = {"P238": {}, "P239": {"AAAA": {"Q9": candidate}}}
    entries = build_entries([make_record(iata_code=None)], candidates)
    assert entries[0].name_zh == "伊卡奥机场"
    assert entries[0].name_zh_source == "wikidata:Q9:zh-hans"


def test_build_entries_municipality_sources() -> None:
    candidates = _candidates("Q1", (10.0, 20.0), {"zh-cn": {"测试国际机场"}})
    wiki_entries = build_entries(
        [make_record()], candidates, city_names={"Testville": "试验城"}
    )
    assert wiki_entries[0].municipality_zh == "试验城"
    assert wiki_entries[0].municipality_zh_source == "wikipedia:en:Testville>zh"
    assert wiki_entries[0].municipality_zh_status == STATUS_RESOLVED

    # P131 是“机场所在地”，不是“服务城市”，只能进 location_zh。
    location_entries = build_entries(
        [make_record()],
        candidates,
        admin_labels={"Q1": [AdminCandidate("Q7", 5000, {"zh-cn": {"试验城市"}})]},
    )
    assert location_entries[0].municipality_zh is None
    assert location_entries[0].municipality_zh_status == STATUS_UNRESOLVED
    assert location_entries[0].location_zh == "试验城市"
    assert location_entries[0].location_zh_source == "wikidata:Q1:P131:Q7:zh-cn"

    missing = build_entries([make_record()], candidates)
    assert missing[0].municipality_zh is None
    assert missing[0].location_zh is None
    assert missing[0].municipality_zh_status == STATUS_UNRESOLVED


def test_build_entries_reports_matched_qids() -> None:
    candidates = _candidates("Q42", (10.0, 20.0), {"zh-cn": {"测试国际机场"}})
    matched: dict[int, str] = {}
    build_entries([make_record()], candidates, matched_qids=matched)
    assert matched == {1: "Q42"}


def test_names_file_round_trip(tmp_path: Path) -> None:
    entry = NameEntry(
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
        municipality_zh_status=STATUS_RESOLVED,
    )
    empty = NameEntry(
        id=2,
        ident="BBB",
        type="medium_airport",
        iata_code=None,
        icao_code=None,
        name="No Name",
        name_zh=None,
        name_zh_source=None,
        municipality=None,
        municipality_zh=None,
        municipality_zh_source=None,
        location_zh="测试镇",
        location_zh_source="wikidata:Q2:P131:Q9:zh-cn",
    )
    path = tmp_path / "names.csv"
    digest = write_names(path, [entry, empty])
    assert len(digest) == 64
    loaded = load_names(path)
    assert loaded[1] == entry
    assert loaded[2].name_zh_status == STATUS_UNRESOLVED
    assert loaded[2].location_zh == "测试镇"
    assert list(loaded) == [1, 2]


def _wiki_client(payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _wiki_payload(pages: list[dict], redirects: list[dict] | None = None) -> dict:
    query: dict = {"pages": pages}
    if redirects:
        query["redirects"] = redirects
    return {"query": query}


def test_wikipedia_city_names_filters() -> None:
    payload = _wiki_payload(
        [
            {
                "title": "Bakersfield, California",
                "categories": [{"title": "Category:Cities in California"}],
                "langlinks": [{"title": "贝克斯菲尔德 (加利福尼亚州)"}],
            },
            {
                "title": "Alabaster",
                "categories": [{"title": "Category:Minerals"}],
                "langlinks": [{"title": "雪花石膏"}],
            },
            {
                "title": "Akita",
                "categories": [{"title": "Category:Disambiguation pages"}],
                "langlinks": [{"title": "秋田號列車"}],
            },
        ],
        redirects=[{"from": "Bakersfield", "to": "Bakersfield, California"}],
    )
    with _wiki_client(payload) as client:
        names = fetch_wikipedia_city_names(client, ["Bakersfield", "Alabaster", "Akita"])
    assert names == {"Bakersfield": "贝克斯菲尔德"}


def test_wikipedia_city_names_handles_missing_page() -> None:
    payload = _wiki_payload([{"title": "Nowhere", "missing": True}])
    with _wiki_client(payload) as client:
        assert fetch_wikipedia_city_names(client, ["Nowhere"]) == {}


def test_admin_labels_query(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_sparql(client, query):  # noqa: ANN001
        captured["query"] = query
        return [
            {
                "ap": {"value": "http://www.wikidata.org/entity/Q1"},
                "admin": {"value": "http://www.wikidata.org/entity/Q7"},
                "adminLabel": {"value": "试验城"},
                "adminLang": {"value": "zh-cn"},
                "population": {"value": "1234"},
            }
        ]

    monkeypatch.setattr(zh_names, "_sparql", fake_sparql)
    with httpx.Client() as client:
        labels = fetch_admin_labels(client, ["Q1"])
    assert labels["Q1"][0].qid == "Q7"
    assert labels["Q1"][0].population == 1234
    assert labels["Q1"][0].labels == {"zh-cn": {"试验城"}}
    assert "wd:Q1" in captured["query"]
    assert "wdt:P131" in captured["query"]
    assert "wd:Q486972" in captured["query"]


def test_best_admin_prefers_population() -> None:
    small = AdminCandidate("Q1", 100, {"zh-cn": {"小镇"}})
    big = AdminCandidate("Q2", 90000, {"zh-cn": {"大城"}})
    assert zh_names._best_admin([small, big]).qid == "Q2"
    assert zh_names._best_admin([]) is None
    nameless = AdminCandidate("Q3", 5, {"zh": {"Town"}})
    assert zh_names._best_admin([nameless]) is None


def test_queries_bind_language() -> None:
    labels_query = zh_names._property_query("P238", ["AAA"])
    assert "BIND(LANG(?label) AS ?lang)" in labels_query
    assert "wdt:P31/wdt:P279* wd:Q1248784" in labels_query
    assert "wdt:P238" in labels_query


def test_wikipedia_city_names_requests_stripped_variant() -> None:
    requested: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        titles = request.url.params["titles"].split("|")
        requested.append(titles)
        pages = []
        for title in titles:
            if title == "Shanghai":
                pages.append(
                    {
                        "title": title,
                        "categories": [{"title": "Category:Cities in China"}],
                        "langlinks": [{"title": "上海市"}],
                    }
                )
            else:
                pages.append({"title": title, "missing": True})
        return httpx.Response(200, json={"query": {"pages": pages}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        names = fetch_wikipedia_city_names(client, ["Shanghai (Pudong)"])
    assert names == {"Shanghai (Pudong)": "上海市"}
    assert requested and "Shanghai" in requested[0]


def test_wikipedia_continues_paginated_response() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if "clcontinue" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "query": {"pages": [{"title": "Springfield", "categories": []}]},
                    "continue": {"clcontinue": "next", "continue": "-||"},
                },
            )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "Springfield",
                            "categories": [{"title": "Category:Cities in Illinois"}],
                            "langlinks": [{"title": "斯普林菲尔德 (伊利诺伊州)"}],
                        }
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        names = fetch_wikipedia_city_names(client, ["Springfield"])
    assert names == {"Springfield": "斯普林菲尔德"}
    assert len(calls) == 2


def test_unresolved_counter_is_not_double_counted() -> None:
    from airports_collector.zh_names import RefreshStats

    stats = RefreshStats()
    build_entries(
        [
            make_record(name="Testville Airport"),
            make_record(id=2, ident="BBB", type="medium_airport", name="Testville Municipal Airport"),
        ],
        {"P238": {}, "P239": {}},
        city_names={"Testville": "试验城"},
        stats=stats,
    )
    # 两条都查不到 Wikidata 实体，但都能用“地名 + 类型”合成 → 最终不应有未解析
    assert stats.composite_resolved == 2
    assert stats.unresolved == 0
    assert stats.target_airports == 2
