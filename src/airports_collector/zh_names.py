"""生成大/中型机场的简体中文名与城市中文名，并冻结为仓库内版本化 CSV。

规则（见 docs/adr/0002）：
1. 机场名先按 IATA(P238)、再按 ICAO(P239) 匹配；实体必须属于机场类（P31/P279* → Q1248784），
   且与 OurAirports 坐标距离 ≤ 25km，命中多个等距实体则判歧义、留空；
2. 标签优先级 zh-cn > zh-hans > zh > zh-hant/zh-tw/zh-hk，统一经 OpenCC 转简体，
   并拒收含 4 个以上连续拉丁字母的混排标签；
3. 城市名（municipality_zh）用英文维基百科跨语言链接，要求页面分类属于居民点、排除消歧义页；
   机场所在地（location_zh）用该机场 Wikidata 实体 P131 中的人类聚居地，多个人选时取人口最多者；
4. 解析不到的一律留空并标 unresolved，不做机器翻译、不猜。
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

from .source import AirportRecord

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "airports-collector/0.1 (+https://github.com/scott-wong/airports)"
AIRPORT_CLASS_QID = "Q1248784"  # airport
HUMAN_SETTLEMENT_QID = "Q486972"  # human settlement：P131 只接受这一类，用来挡掉省份/岛屿
MAX_DISTANCE_KM = 25.0
AMBIGUITY_RADIUS_KM = 1.0
CODE_CHUNK_SIZE = 200
QID_CHUNK_SIZE = 200
WIKI_BATCH_SIZE = 50
SPARQL_ATTEMPTS = 4
SPARQL_BACKOFF_SECONDS = (2.0, 6.0, 15.0)

# 只有这两类机场要求补中文名；其余类型不查。
TARGET_TYPES = frozenset({"large_airport", "medium_airport"})

ZH_LANG_PREFERENCE = ("zh-cn", "zh-hans", "zh", "zh-hant", "zh-tw", "zh-hk")
TRADITIONAL_LANGS = frozenset({"zh-hant", "zh-tw", "zh-hk"})
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{4,}")
POINT_RE = re.compile(r"Point\(([-0-9.eE]+)\s+([-0-9.eE]+)\)")
PARENTHETICAL_RE = re.compile(r"\s*[（(][^）)]*[）)]\s*$")

# 英文维基百科上视为“居民点”的分类关键词；用于挡掉 Alabaster（矿石）、Akita（列车）这类错配。
SETTLEMENT_CATEGORY_HINTS = (
    "populated places",
    "populated place",
    "cities",
    "city",
    "towns",
    "town",
    "municipalities",
    "municipality",
    "villages",
    "village",
    "census-designated places",
    "districts",
    "district",
    "neighborhoods",
    "suburbs",
    "boroughs",
    "communes",
    "settlements",
    "counties",
)

NAME_COLUMNS: tuple[str, ...] = (
    "id",
    "ident",
    "type",
    "iata_code",
    "icao_code",
    "name",
    "name_zh",
    "name_zh_source",
    "name_zh_status",
    "municipality",
    "municipality_zh",
    "municipality_zh_source",
    "municipality_zh_status",
    "location_zh",
    "location_zh_source",
)

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"


class ZhNamesError(RuntimeError):
    """中文名生成失败。"""


@dataclass(frozen=True)
class NameEntry:
    id: int
    ident: str
    type: str
    iata_code: str | None
    icao_code: str | None
    name: str
    name_zh: str | None
    name_zh_source: str | None
    municipality: str | None
    municipality_zh: str | None
    municipality_zh_source: str | None
    name_zh_status: str = STATUS_UNRESOLVED
    municipality_zh_status: str = STATUS_UNRESOLVED
    location_zh: str | None = None
    location_zh_source: str | None = None

    def to_row(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "ident": self.ident,
            "type": self.type,
            "iata_code": self.iata_code or "",
            "icao_code": self.icao_code or "",
            "name": self.name,
            "name_zh": self.name_zh or "",
            "name_zh_source": self.name_zh_source or "",
            "name_zh_status": self.name_zh_status,
            "municipality": self.municipality or "",
            "municipality_zh": self.municipality_zh or "",
            "municipality_zh_source": self.municipality_zh_source or "",
            "municipality_zh_status": self.municipality_zh_status,
            "location_zh": self.location_zh or "",
            "location_zh_source": self.location_zh_source or "",
        }


@dataclass
class RefreshStats:
    target_airports: int = 0
    resolved: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    via_iata: int = 0
    via_icao: int = 0
    converted_from_traditional: int = 0
    municipality_from_wikipedia: int = 0
    municipality_unresolved: int = 0
    location_from_wikidata: int = 0
    location_unresolved: int = 0

    def summary(self) -> str:
        return (
            f"目标机场 {self.target_airports} 条：中文名 {self.resolved} 条"
            f"（IATA {self.via_iata} / ICAO {self.via_icao}），未解析 {self.unresolved} 条，"
            f"实体有歧义 {self.ambiguous} 条，繁转简 {self.converted_from_traditional} 条；"
            f"城市中文名（municipality_zh）{self.municipality_from_wikipedia} 条，"
            f"未解析 {self.municipality_unresolved} 条；"
            f"所在地中文名（location_zh）{self.location_from_wikidata} 条，"
            f"未解析 {self.location_unresolved} 条"
        )


_converter: Any | None = None


def _converter_instance() -> Any:
    global _converter
    if _converter is None:
        try:
            from opencc import OpenCC  # type: ignore import-not-found

            _converter = OpenCC("t2s")
        except Exception:  # pragma: no cover - 依赖缺失时退化
            _converter = False
    return _converter


def _to_simplified(text: str) -> str:
    converter = _converter_instance()
    if converter is False:
        return text
    return str(converter.convert(text))


def _is_valid_zh(text: str) -> bool:
    return bool(CJK_RE.search(text))


def parse_point(wkt: str | None) -> tuple[float, float] | None:
    """WKT Point(lon lat) → (lat, lon)。"""
    if not wkt:
        return None
    match = POINT_RE.search(wkt)
    if not match:
        return None
    lon, lat = float(match.group(1)), float(match.group(2))
    return lat, lon


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def choose_label(labels: dict[str, set[str]]) -> tuple[str, str, bool] | None:
    """按优先级选出中文标签，返回 (文本, 来源后缀, 是否经过繁转简)。"""
    for lang in ZH_LANG_PREFERENCE:
        candidates = labels.get(lang)
        if not candidates:
            continue
        for candidate in sorted(candidates):
            text = candidate.strip()
            if not _is_valid_zh(text) or LATIN_WORD_RE.search(text):
                continue
            simplified = _to_simplified(text)
            converted = simplified != text or lang in TRADITIONAL_LANGS
            suffix = f"{lang}>zh-hans" if converted else lang
            return simplified, suffix, converted
    return None


def clean_wiki_title(title: str) -> str | None:
    """去掉维基条目的消歧义括号并转简体；不合法时返回 None。"""
    text = PARENTHETICAL_RE.sub("", title).strip()
    if not _is_valid_zh(text) or LATIN_WORD_RE.search(text):
        return None
    return _to_simplified(text)


def _values_clause(codes: Sequence[str]) -> str:
    return " ".join(f'"{code}"' for code in codes)


def _values_qids(qids: Sequence[str]) -> str:
    return " ".join(f"wd:{qid}" for qid in qids)


def _sparql(http_client: httpx.Client, query: str) -> list[dict[str, Any]]:
    """带重试的 SPARQL 查询：公共端点在高峰期会返回 502/429/超时。"""
    last_error: str | None = None
    for attempt in range(SPARQL_ATTEMPTS):
        if attempt:
            time.sleep(SPARQL_BACKOFF_SECONDS[min(attempt - 1, len(SPARQL_BACKOFF_SECONDS) - 1)])
        try:
            response = http_client.post(
                WIKIDATA_ENDPOINT,
                data={"query": query, "format": "json"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=180.0,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = f"HTTP {response.status_code}"
                continue
            response.raise_for_status()
            payload = response.json()
        except httpx.TransportError as error:
            last_error = f"{type(error).__name__}: {error}"
            continue
        except httpx.HTTPStatusError as error:
            raise ZhNamesError(f"Wikidata 查询失败: {error}") from error
        except ValueError:
            last_error = "非 JSON 响应"
            continue
        try:
            return payload["results"]["bindings"]
        except (KeyError, TypeError) as error:
            raise ZhNamesError(f"Wikidata 响应结构异常: {str(payload)[:200]}") from error
    raise ZhNamesError(f"Wikidata 查询连续 {SPARQL_ATTEMPTS} 次失败（最后错误：{last_error}）")


def _property_query(property_id: str, codes: Sequence[str]) -> str:
    values = _values_clause(codes)
    langs = ", ".join(repr(lang) for lang in ZH_LANG_PREFERENCE)
    optional = (
        "OPTIONAL { ?ap wdt:P625 ?coord . } "
        "OPTIONAL { ?ap rdfs:label ?label . BIND(LANG(?label) AS ?lang) "
        f"FILTER(?lang IN ({langs})) }}"
    )
    return f"""
SELECT ?code ?ap ?coord ?label ?lang WHERE {{
  VALUES ?code {{ {values} }}
  ?ap wdt:{property_id} ?code .
  ?ap wdt:P31/wdt:P279* wd:{AIRPORT_CLASS_QID} .
  {optional}
}}
"""


def _admin_query(qids: Sequence[str]) -> str:
    langs = ", ".join(repr(lang) for lang in ZH_LANG_PREFERENCE)
    return f"""
SELECT ?ap ?admin ?adminLabel ?adminLang ?population WHERE {{
  VALUES ?ap {{ {_values_qids(qids)} }}
  ?ap wdt:P131 ?admin .
  ?admin wdt:P31/wdt:P279* wd:{HUMAN_SETTLEMENT_QID} .
  OPTIONAL {{ ?admin wdt:P1082 ?population . }}
  ?admin rdfs:label ?adminLabel .
  BIND(LANG(?adminLabel) AS ?adminLang)
  FILTER(?adminLang IN ({langs}))
}}
"""


@dataclass
class Candidate:
    qid: str
    coord: tuple[float, float] | None
    labels: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class AdminCandidate:
    """Airport P131 指向的聚居地实体。"""

    qid: str
    population: int | None = None
    labels: dict[str, set[str]] = field(default_factory=dict)


def _fetch_candidates(
    http_client: httpx.Client,
    property_id: str,
    codes: Sequence[str],
    *,
    on_progress: Any | None = None,
) -> dict[str, dict[str, Candidate]]:
    result: dict[str, dict[str, Candidate]] = {}
    if not codes:
        return result
    chunks = [codes[i : i + CODE_CHUNK_SIZE] for i in range(0, len(codes), CODE_CHUNK_SIZE)]
    for index, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(f"  查询 {property_id} 第 {index}/{len(chunks)} 批（{len(chunk)} 个代码）")
        rows = _sparql(http_client, _property_query(property_id, chunk))
        for row in rows:
            code = row["code"]["value"]
            qid = row["ap"]["value"].rsplit("/", 1)[-1]
            candidate = result.setdefault(code, {}).setdefault(qid, Candidate(qid, None))
            coord = parse_point(row.get("coord", {}).get("value"))
            if coord and candidate.coord is None:
                candidate.coord = coord
            label = row.get("label", {}).get("value")
            lang = row.get("lang", {}).get("value")
            if label and lang:
                candidate.labels.setdefault(lang, set()).add(label)
        if on_progress:
            on_progress(f"  {property_id} 第 {index} 批返回 {len(rows)} 行")
        if len(chunks) > 1:
            time.sleep(0.5)
    return result


def fetch_admin_labels(
    http_client: httpx.Client,
    qids: Sequence[str],
    *,
    on_progress: Any | None = None,
) -> dict[str, list[AdminCandidate]]:
    """取机场实体 P131 中属于“人类聚居地”的中文标签，作为城市名兜底。

    只接受 Q486972（human settlement）及其子类：省份、岛屿、专区会被挡掉，
    避免出现 Honiara → 瓜达尔卡纳尔省 这种把省名当城市名的错。
    """
    result: dict[str, dict[str, AdminCandidate]] = {}
    if not qids:
        return {}
    chunks = [qids[i : i + QID_CHUNK_SIZE] for i in range(0, len(qids), QID_CHUNK_SIZE)]
    for index, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(f"  查询 P131 第 {index}/{len(chunks)} 批（{len(chunk)} 个实体）")
        rows = _sparql(http_client, _admin_query(chunk))
        for row in rows:
            qid = row["ap"]["value"].rsplit("/", 1)[-1]
            admin_qid = row["admin"]["value"].rsplit("/", 1)[-1]
            label = row.get("adminLabel", {}).get("value")
            lang = row.get("adminLang", {}).get("value")
            population_raw = row.get("population", {}).get("value")
            candidate = result.setdefault(qid, {}).setdefault(
                admin_qid, AdminCandidate(admin_qid, None)
            )
            if population_raw:
                try:
                    population = int(float(population_raw))
                except ValueError:
                    population = None
                if population is not None and (
                    candidate.population is None or population > candidate.population
                ):
                    candidate.population = population
            if label and lang:
                candidate.labels.setdefault(lang, set()).add(label)
        if len(chunks) > 1:
            time.sleep(0.5)
    return {qid: list(candidates.values()) for qid, candidates in result.items()}


def _wikipedia_request(
    http_client: httpx.Client, titles: Sequence[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """一次 MediaWiki query 请求，返回 (page_title → page, 请求标题 → 最终标题)。

    自动跟随 continue：一次请求 50 个标题时 MediaWiki 会分批返回 langlinks/categories，
    不跟随就会丢掉大部分页面（这正是 Beijing 解析不出来的原因）。
    """
    params: dict[str, Any] = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "langlinks|categories",
        "lllang": "zh",
        "cllimit": "max",
        "redirects": "1",
        "titles": "|".join(titles),
    }
    pages: dict[str, dict[str, Any]] = {}
    mapping: dict[str, str] = {}
    while True:
        try:
            response = http_client.get(
                WIKIPEDIA_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=60.0
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as error:
            raise ZhNamesError(f"维基百科查询失败: {error}") from error
        except ValueError as error:
            raise ZhNamesError("维基百科返回了非 JSON 响应") from error
        if not isinstance(payload, dict):
            raise ZhNamesError("维基百科响应结构异常")
        if "error" in payload:
            raise ZhNamesError(f"维基百科返回错误: {str(payload['error'])[:200]}")
        query = payload.get("query", {})
        for item in query.get("normalized", []):
            mapping[item["from"]] = item["to"]
        for item in query.get("redirects", []):
            mapping[item["from"]] = item["to"]
        for page in query.get("pages", []):
            title = page.get("title")
            if not title:
                continue
            existing = pages.get(title)
            if existing is None:
                pages[title] = page
                continue
            merged_categories = {c["title"] for c in existing.get("categories", [])}
            merged_categories.update(c["title"] for c in page.get("categories", []))
            existing["categories"] = [{"title": name} for name in sorted(merged_categories)]
            if not existing.get("langlinks") and page.get("langlinks"):
                existing["langlinks"] = page["langlinks"]
        continuation = payload.get("continue")
        if not continuation:
            break
        params.update(continuation)
    return pages, mapping


def _wikipedia_pages(
    http_client: httpx.Client, titles: Sequence[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """批量查询，整批报错时二分降级到单条标题，避免一条坏标题拖垮 50 条。"""
    try:
        return _wikipedia_request(http_client, titles)
    except ZhNamesError:
        if len(titles) == 1:
            return {}, {}
        middle = len(titles) // 2
        left_pages, left_map = _wikipedia_pages(http_client, list(titles[:middle]))
        right_pages, right_map = _wikipedia_pages(http_client, list(titles[middle:]))
        return {**left_pages, **right_pages}, {**left_map, **right_map}


def _resolve_title(requested: str, mapping: dict[str, str]) -> str:
    title = requested
    for _ in range(3):
        next_title = mapping.get(title)
        if not next_title or next_title == title:
            break
        title = next_title
    return title


def _city_title_variants(city: str) -> list[str]:
    """OurAirports 的 municipality 常带括号后缀，例如 Shanghai (Pudong)。"""
    variants = [city]
    stripped = PARENTHETICAL_RE.sub("", city).strip()
    if stripped and stripped != city:
        variants.append(stripped)
    return variants


def fetch_wikipedia_city_names(
    http_client: httpx.Client,
    cities: Sequence[str],
    *,
    on_progress: Any | None = None,
) -> dict[str, str]:
    """英文维基条目标题 → 中文条目名，只接受居民点分类、排除消歧义页。"""
    result: dict[str, str] = {}
    if not cities:
        return result
    # 变体（去掉括号后缀）必须一起进请求，否则 API 不会返回它们的页面。
    batches: list[tuple[list[str], list[str]]] = []
    current_cities: list[str] = []
    current_titles: list[str] = []
    for city in cities:
        variants = _city_title_variants(city)
        if current_titles and len(current_titles) + len(variants) > WIKI_BATCH_SIZE:
            batches.append((current_cities, current_titles))
            current_cities, current_titles = [], []
        current_cities.append(city)
        for variant in variants:
            if variant not in current_titles:
                current_titles.append(variant)
    if current_cities:
        batches.append((current_cities, current_titles))

    for index, (chunk, titles) in enumerate(batches, start=1):
        if on_progress and (index == 1 or index % 10 == 0 or index == len(batches)):
            on_progress(f"  维基百科城市名 第 {index}/{len(batches)} 批")
        pages, mapping = _wikipedia_pages(http_client, titles)
        for city in chunk:
            for variant in _city_title_variants(city):
                page = pages.get(_resolve_title(variant, mapping))
                if not page or page.get("missing"):
                    continue
                categories = [item["title"].lower() for item in page.get("categories", [])]
                if any("disambiguation" in category for category in categories):
                    continue
                if not any(
                    hint in category for category in categories for hint in SETTLEMENT_CATEGORY_HINTS
                ):
                    continue
                langlinks = page.get("langlinks") or []
                if not langlinks:
                    continue
                cleaned = clean_wiki_title(str(langlinks[0]["title"]))
                if cleaned:
                    result[city] = cleaned
                    break
        time.sleep(0.2)
    return result


@dataclass
class Match:
    candidate: Candidate
    property_id: str
    ambiguous: bool


def _match(
    codes: dict[str, str | None],
    latitude: float | None,
    longitude: float | None,
    candidates_by_property: dict[str, dict[str, dict[str, Candidate]]],
) -> Match | None:
    for property_id in ("P238", "P239"):
        code = codes.get(property_id)
        if not code:
            continue
        candidates = candidates_by_property.get(property_id, {}).get(code)
        if not candidates:
            continue
        scored: list[tuple[float, Candidate]] = []
        for candidate in candidates.values():
            if candidate.coord is None:
                continue
            if latitude is None or longitude is None:
                scored.append((0.0, candidate))
                continue
            distance = distance_km(latitude, longitude, candidate.coord[0], candidate.coord[1])
            if distance <= MAX_DISTANCE_KM:
                scored.append((distance, candidate))
        if not scored:
            continue
        scored.sort(key=lambda item: (item[0], item[1].qid))
        ambiguous = False
        if len(scored) > 1 and abs(scored[1][0] - scored[0][0]) < AMBIGUITY_RADIUS_KM:
            ambiguous = True
        return Match(candidate=scored[0][1], property_id=property_id, ambiguous=ambiguous)
    return None


def _best_admin(candidates: Sequence[AdminCandidate]) -> AdminCandidate | None:
    """多个人类聚居地时取人口最多的；人口缺失按 0 处理，保证结果稳定。"""
    usable = [candidate for candidate in candidates if choose_label(candidate.labels)]
    if not usable:
        return None
    return sorted(usable, key=lambda item: (-(item.population or 0), item.qid))[0]


def build_entries(
    records: Sequence[AirportRecord],
    candidates_by_property: dict[str, dict[str, dict[str, Candidate]]],
    *,
    city_names: dict[str, str] | None = None,
    admin_labels: dict[str, list[AdminCandidate]] | None = None,
    stats: RefreshStats | None = None,
    matched_qids: dict[int, str] | None = None,
) -> list[NameEntry]:
    stats = stats or RefreshStats()
    city_names = city_names or {}
    admin_labels = admin_labels or {}
    entries: list[NameEntry] = []
    for record in records:
        if record.type not in TARGET_TYPES:
            continue
        stats.target_airports += 1
        match = _match(
            {"P238": record.iata_code, "P239": record.icao_code},
            record.latitude_deg,
            record.longitude_deg,
            candidates_by_property,
        )
        if match is not None and match.ambiguous:
            stats.ambiguous += 1
            match = None
        if match is not None and matched_qids is not None:
            matched_qids[record.id] = match.candidate.qid

        name_zh = name_source = None
        name_status = STATUS_UNRESOLVED
        if match is not None:
            chosen = choose_label(match.candidate.labels)
            if chosen is not None:
                name_zh, suffix, converted = chosen
                name_source = f"wikidata:{match.candidate.qid}:{suffix}"
                name_status = STATUS_RESOLVED
                stats.resolved += 1
                if match.property_id == "P238":
                    stats.via_iata += 1
                else:
                    stats.via_icao += 1
                if converted:
                    stats.converted_from_traditional += 1
        if name_status == STATUS_UNRESOLVED:
            stats.unresolved += 1

        municipality_zh = municipality_source = None
        municipality_status = STATUS_UNRESOLVED
        if record.municipality:
            wiki_name = city_names.get(record.municipality)
            if wiki_name:
                municipality_zh = wiki_name
                municipality_source = f"wikipedia:en:{record.municipality}>zh"
                municipality_status = STATUS_RESOLVED
                stats.municipality_from_wikipedia += 1
            else:
                stats.municipality_unresolved += 1

        location_zh = location_source = None
        if match is not None:
            admin = _best_admin(admin_labels.get(match.candidate.qid, []))
            if admin is not None:
                chosen_admin = choose_label(admin.labels)
                if chosen_admin is not None:
                    location_zh, admin_suffix, _ = chosen_admin
                    location_source = (
                        f"wikidata:{match.candidate.qid}:P131:{admin.qid}:{admin_suffix}"
                    )
                    stats.location_from_wikidata += 1
        if location_zh is None:
            stats.location_unresolved += 1

        entries.append(
            NameEntry(
                id=record.id,
                ident=record.ident,
                type=record.type,
                iata_code=record.iata_code,
                icao_code=record.icao_code,
                name=record.name,
                name_zh=name_zh,
                name_zh_source=name_source,
                municipality=record.municipality,
                municipality_zh=municipality_zh,
                municipality_zh_source=municipality_source,
                name_zh_status=name_status,
                municipality_zh_status=municipality_status,
                location_zh=location_zh,
                location_zh_source=location_source,
            )
        )
    entries.sort(key=lambda entry: entry.id)
    return entries


def write_names(path: Path, entries: Iterable[NameEntry]) -> str:
    import hashlib

    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(NAME_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for entry in entries:
        writer.writerow(entry.to_row())
    content = buffer.getvalue()
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _optional(value: str | None) -> str | None:
    return value or None


def load_names(path: Path) -> dict[int, NameEntry]:
    if not path.exists():
        raise ZhNamesError(f"中文名文件不存在: {path}（先运行 names refresh，或用 --allow-missing-names）")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        if header != NAME_COLUMNS:
            raise ZhNamesError(f"{path} 表头不符合预期: {header}")
        entries: dict[int, NameEntry] = {}
        for row in reader:
            record_id = int(row["id"])
            entries[record_id] = NameEntry(
                id=record_id,
                ident=row["ident"],
                type=row["type"],
                iata_code=_optional(row["iata_code"]),
                icao_code=_optional(row["icao_code"]),
                name=row["name"],
                name_zh=_optional(row["name_zh"]),
                name_zh_source=_optional(row["name_zh_source"]),
                municipality=_optional(row["municipality"]),
                municipality_zh=_optional(row["municipality_zh"]),
                municipality_zh_source=_optional(row["municipality_zh_source"]),
                name_zh_status=row["name_zh_status"],
                municipality_zh_status=row["municipality_zh_status"],
                location_zh=_optional(row["location_zh"]),
                location_zh_source=_optional(row["location_zh_source"]),
            )
    return entries


def file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh_names(
    http_client: httpx.Client,
    records: Sequence[AirportRecord],
    out_path: Path,
    *,
    on_progress: Any | None = None,
) -> RefreshStats:
    targets = [record for record in records if record.type in TARGET_TYPES]
    iata_codes = sorted({record.iata_code for record in targets if record.iata_code})
    if on_progress:
        on_progress(f"目标机场 {len(targets)} 条（large + medium）；IATA {len(iata_codes)} 个待查")
    candidates: dict[str, dict[str, dict[str, Candidate]]] = {
        "P238": _fetch_candidates(http_client, "P238", iata_codes, on_progress=on_progress),
        "P239": {},
    }
    matched: dict[int, str] = {}
    entries = build_entries(targets, candidates, matched_qids=matched)

    unresolved_ids = {entry.id for entry in entries if entry.name_zh_status == STATUS_UNRESOLVED}
    fallback_codes = sorted(
        {record.icao_code for record in targets if record.id in unresolved_ids and record.icao_code}
    )
    if fallback_codes:
        if on_progress:
            on_progress(f"IATA 未解析，改用 ICAO 兜底查询 {len(fallback_codes)} 个代码")
        candidates["P239"] = _fetch_candidates(
            http_client, "P239", fallback_codes, on_progress=on_progress
        )
        matched = {}
        entries = build_entries(targets, candidates, matched_qids=matched)

    admin_labels = fetch_admin_labels(
        http_client, sorted(set(matched.values())), on_progress=on_progress
    )
    cities = sorted({record.municipality for record in targets if record.municipality})
    city_names = fetch_wikipedia_city_names(http_client, cities, on_progress=on_progress)

    stats = RefreshStats()
    matched = {}
    entries = build_entries(
        targets,
        candidates,
        city_names=city_names,
        admin_labels=admin_labels,
        stats=stats,
        matched_qids=matched,
    )
    digest = write_names(out_path, entries)
    if on_progress:
        on_progress(f"已写入 {out_path}（sha256 {digest[:12]}…）")
    return stats
