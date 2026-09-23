"""从 Wikidata 生成大机场的简体中文名，并冻结为仓库内版本化 CSV。

规则（见 docs/adr/0002）：
1. 先按 IATA(P238) 匹配，再按 ICAO(P239) 兜底；
2. 实体必须属于机场类（P31/P279* → Q1248784），且坐标距离 ≤ 25km；
3. 标签优先级 zh-cn > zh-hans > zh > zh-hant/zh-tw/zh-hk，统一经 OpenCC 转简体，
   并拒收含 4 个以上连续拉丁字母的混排标签；
4. 匹配不到或标签缺失时留空并标 unresolved，绝不猜。
5. v1 不填充 municipality_zh：Wikidata P131 常给出比“服务城市”更细的行政区
   （如北京大兴 → 九州镇），按城市名另做匹配的查询会超时，故留空待后续处理。
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

from .source import AirportRecord

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "airports-collector/0.1 (+https://github.com/scott-wong/airports)"
AIRPORT_CLASS_QID = "Q1248784"  # airport
MAX_DISTANCE_KM = 25.0
AMBIGUITY_RADIUS_KM = 1.0
CODE_CHUNK_SIZE = 200
SPARQL_ATTEMPTS = 4
SPARQL_BACKOFF_SECONDS = (2.0, 6.0, 15.0)

ZH_LANG_PREFERENCE = ("zh-cn", "zh-hans", "zh", "zh-hant", "zh-tw", "zh-hk")
TRADITIONAL_LANGS = frozenset({"zh-hant", "zh-tw", "zh-hk"})
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{4,}")
POINT_RE = re.compile(r"Point\(([-0-9.eE]+)\s+([-0-9.eE]+)\)")

NAME_COLUMNS: tuple[str, ...] = (
    "id",
    "ident",
    "iata_code",
    "icao_code",
    "name",
    "name_zh",
    "name_zh_source",
    "municipality",
    "municipality_zh",
    "municipality_zh_source",
    "status",
)

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"


class ZhNamesError(RuntimeError):
    """中文名生成失败。"""


@dataclass(frozen=True)
class NameEntry:
    id: int
    ident: str
    iata_code: str | None
    icao_code: str | None
    name: str
    name_zh: str | None
    name_zh_source: str | None
    municipality: str | None
    municipality_zh: str | None
    municipality_zh_source: str | None
    status: str

    def to_row(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "ident": self.ident,
            "iata_code": self.iata_code or "",
            "icao_code": self.icao_code or "",
            "name": self.name,
            "name_zh": self.name_zh or "",
            "name_zh_source": self.name_zh_source or "",
            "municipality": self.municipality or "",
            "municipality_zh": self.municipality_zh or "",
            "municipality_zh_source": self.municipality_zh_source or "",
            "status": self.status,
        }


@dataclass
class RefreshStats:
    total_large_airports: int = 0
    resolved: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    via_iata: int = 0
    via_icao: int = 0
    converted_from_traditional: int = 0

    def summary(self) -> str:
        return (
            f"大机场 {self.total_large_airports} 条："
            f"中文名 {self.resolved} 条（IATA {self.via_iata} / ICAO {self.via_icao}），"
            f"未解析 {self.unresolved} 条，实体有歧义 {self.ambiguous} 条，"
            f"繁转简 {self.converted_from_traditional} 条"
        )


_converter: Any | None = None


def _to_simplified(text: str) -> str:
    global _converter
    if _converter is None:
        try:
            from opencc import OpenCC  # type: ignore import-not-found

            _converter = OpenCC("t2s")
        except Exception:  # pragma: no cover - 依赖缺失时退化
            _converter = False
    if _converter is False:
        return text
    return str(_converter.convert(text))


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
    """按优先级选出中文标签，返回 (文本, 来源后缀, 是否经过繁转简)。

    Wikidata 的 zh 标签可能是繁体、也可能混着英文单词（如 "Akanu Ibiam國際機場"），
    这里统一做繁转简，并拒收含 4 个以上连续拉丁字母的标签。
    """
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


def _values_clause(codes: Sequence[str]) -> str:
    return " ".join(f'"{code}"' for code in codes)


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
        except ValueError as error:
            last_error = "非 JSON 响应"
            continue
        try:
            return payload["results"]["bindings"]
        except (KeyError, TypeError) as error:
            raise ZhNamesError(f"Wikidata 响应结构异常: {str(payload)[:200]}") from error
    raise ZhNamesError(f"Wikidata 查询连续 {SPARQL_ATTEMPTS} 次失败（最后错误：{last_error}）")


def _property_query(property_id: str, codes: Sequence[str]) -> str:
    values = _values_clause(codes)
    select = "?code ?ap ?coord ?label ?lang"
    langs = ", ".join(repr(lang) for lang in ZH_LANG_PREFERENCE)
    optional = (
        "OPTIONAL { ?ap wdt:P625 ?coord . } "
        "OPTIONAL { ?ap rdfs:label ?label . BIND(LANG(?label) AS ?lang) "
        f"FILTER(?lang IN ({langs})) }}"
    )
    return f"""
SELECT {select} WHERE {{
  VALUES ?code {{ {values} }}
  ?ap wdt:{property_id} ?code .
  ?ap wdt:P31/wdt:P279* wd:{AIRPORT_CLASS_QID} .
  {optional}
}}
"""


@dataclass
class Candidate:
    qid: str
    coord: tuple[float, float] | None
    labels: dict[str, set[str]]


def _fetch_candidates(
    http_client: httpx.Client,
    property_id: str,
    codes: Sequence[str],
    *,
    on_progress: Any | None = None,
) -> dict[str, dict[str, Candidate]]:
    result: dict[str, dict[str, Candidate]] = {}
    chunks = [codes[i : i + CODE_CHUNK_SIZE] for i in range(0, len(codes), CODE_CHUNK_SIZE)]
    for index, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(f"  查询 {property_id} 第 {index}/{len(chunks)} 批（{len(chunk)} 个代码）")
        rows = _sparql(http_client, _property_query(property_id, chunk))
        for row in rows:
            code = row["code"]["value"]
            qid = row["ap"]["value"].rsplit("/", 1)[-1]
            candidate = result.setdefault(code, {}).setdefault(qid, Candidate(qid, None, {}))
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


def build_entries(
    records: Sequence[AirportRecord],
    candidates_by_property: dict[str, dict[str, dict[str, Candidate]]],
    *,
    stats: RefreshStats | None = None,
) -> list[NameEntry]:
    stats = stats or RefreshStats()
    entries: list[NameEntry] = []
    for record in records:
        if record.type != "large_airport":
            continue
        stats.total_large_airports += 1
        match = _match(
            {"P238": record.iata_code, "P239": record.icao_code},
            record.latitude_deg,
            record.longitude_deg,
            candidates_by_property,
        )
        name_zh = name_source = municipality_zh = municipality_source = None
        status = STATUS_UNRESOLVED
        if match is not None:
            if match.ambiguous:
                stats.ambiguous += 1
                match = None
        if match is not None:
            chosen = choose_label(match.candidate.labels)
            if chosen is not None:
                name_zh, suffix, converted = chosen
                name_source = f"wikidata:{match.candidate.qid}:{suffix}"
                status = STATUS_RESOLVED
                stats.resolved += 1
                if match.property_id == "P238":
                    stats.via_iata += 1
                else:
                    stats.via_icao += 1
                if converted:
                    stats.converted_from_traditional += 1
        if status == STATUS_UNRESOLVED:
            stats.unresolved += 1
        entries.append(
            NameEntry(
                id=record.id,
                ident=record.ident,
                iata_code=record.iata_code,
                icao_code=record.icao_code,
                name=record.name,
                name_zh=name_zh,
                name_zh_source=name_source,
                municipality=record.municipality,
                municipality_zh=municipality_zh,
                municipality_zh_source=municipality_source,
                status=status,
            )
        )
    entries.sort(key=lambda entry: entry.id)
    return entries


def write_names(path: Path, entries: Iterable[NameEntry]) -> str:
    """写入 CSV 并返回内容 sha256。"""
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
                iata_code=row["iata_code"] or None,
                icao_code=row["icao_code"] or None,
                name=row["name"],
                name_zh=row["name_zh"] or None,
                name_zh_source=row["name_zh_source"] or None,
                municipality=row["municipality"] or None,
                municipality_zh=row["municipality_zh"] or None,
                municipality_zh_source=row["municipality_zh_source"] or None,
                status=row["status"],
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
    large = [record for record in records if record.type == "large_airport"]
    iata_codes = sorted({record.iata_code for record in large if record.iata_code})
    icao_codes = sorted({record.icao_code for record in large if record.icao_code})
    if on_progress:
        on_progress(f"大机场 {len(large)} 条；IATA {len(iata_codes)} 个、ICAO {len(icao_codes)} 个待查")
    candidates: dict[str, dict[str, dict[str, Candidate]]] = {
        "P238": _fetch_candidates(http_client, "P238", iata_codes, on_progress=on_progress),
        "P239": {},
    }
    stats = RefreshStats()
    entries = build_entries(large, candidates, stats=stats)
    unresolved_ids = {entry.id for entry in entries if entry.status == STATUS_UNRESOLVED}
    fallback_codes = sorted(
        {
            record.icao_code
            for record in large
            if record.id in unresolved_ids and record.icao_code
        }
    )
    if fallback_codes:
        if on_progress:
            on_progress(f"IATA 未解析，改用 ICAO 兜底查询 {len(fallback_codes)} 个代码")
        candidates["P239"] = _fetch_candidates(
            http_client, "P239", fallback_codes, on_progress=on_progress
        )
        stats = RefreshStats()
        entries = build_entries(large, candidates, stats=stats)
    digest = write_names(out_path, entries)
    if on_progress:
        on_progress(f"已写入 {out_path}（sha256 {digest[:12]}…）")
    return stats
