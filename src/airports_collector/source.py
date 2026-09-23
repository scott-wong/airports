from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import httpx

SOURCE_COLUMNS: tuple[str, ...] = (
    "id",
    "ident",
    "type",
    "name",
    "latitude_deg",
    "longitude_deg",
    "elevation_ft",
    "continent",
    "iso_country",
    "iso_region",
    "municipality",
    "scheduled_service",
    "gps_code",
    "icao_code",
    "iata_code",
    "local_code",
    "home_link",
    "wikipedia_link",
    "keywords",
)

# 数据字典写的是 closed_airport，实际 CSV 里是 closed；按实际数据校验。
ALLOWED_TYPES: frozenset[str] = frozenset(
    {
        "balloonport",
        "closed",
        "heliport",
        "large_airport",
        "medium_airport",
        "seaplane_base",
        "small_airport",
    }
)
ALLOWED_CONTINENTS: frozenset[str] = frozenset({"AF", "AN", "AS", "EU", "NA", "OC", "SA"})
ALLOWED_SCHEDULED_SERVICE: frozenset[str] = frozenset({"yes", "no"})

MIN_EXPECTED_ROWS = 50_000
MIN_EXPECTED_LARGE_AIRPORTS = 1_000


class SourceError(RuntimeError):
    """下载或校验源数据失败。"""


@dataclass(frozen=True)
class AirportRecord:
    id: int
    ident: str
    type: str
    name: str
    latitude_deg: float | None
    longitude_deg: float | None
    elevation_ft: int | None
    continent: str | None
    iso_country: str | None
    iso_region: str | None
    municipality: str | None
    scheduled_service: str | None
    gps_code: str | None
    icao_code: str | None
    iata_code: str | None
    local_code: str | None
    home_link: str | None
    wikipedia_link: str | None
    keywords: str | None

    def source_values(self) -> tuple[Any, ...]:
        return (
            self.id,
            self.ident,
            self.type,
            self.name,
            self.latitude_deg,
            self.longitude_deg,
            self.elevation_ft,
            self.continent,
            self.iso_country,
            self.iso_region,
            self.municipality,
            self.scheduled_service,
            self.gps_code,
            self.icao_code,
            self.iata_code,
            self.local_code,
            self.home_link,
            self.wikipedia_link,
            self.keywords,
        )

    @property
    def row_hash(self) -> str:
        return compute_row_hash(self.source_values())


@dataclass(frozen=True)
class DownloadResult:
    content: bytes
    etag: str | None
    last_modified: str | None
    sha256: str
    source_url: str


def compute_row_hash(values: Iterable[Any]) -> str:
    payload = json.dumps(list(values), ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def download_airports(source_url: str, http_client: httpx.Client) -> DownloadResult:
    """整份下载。不做条件请求：每轮都要看到全部记录，才能正确判断失活。"""
    headers = {"User-Agent": "airports-collector/0.1 (+https://github.com/scott-wong/airports)"}
    try:
        response = http_client.get(source_url, headers=headers, timeout=120.0, follow_redirects=True)
    except httpx.HTTPError as error:
        raise SourceError(f"下载 {source_url} 失败: {error}") from error
    if response.status_code != 200:
        raise SourceError(f"下载 {source_url} 返回 HTTP {response.status_code}")
    content = response.content
    if not content:
        raise SourceError("下载内容为空")
    return DownloadResult(
        content=content,
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
        sha256=hash_bytes(content),
        source_url=source_url,
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_int(raw: str, field: str, line_number: int) -> int:
    try:
        return int(raw)
    except ValueError as error:
        raise SourceError(f"第 {line_number} 行 {field} 不是整数: {raw!r}") from error


def _parse_optional_int(raw: str | None, field: str, line_number: int) -> int | None:
    cleaned = _clean(raw)
    if cleaned is None:
        return None
    try:
        return int(float(cleaned))
    except ValueError as error:
        raise SourceError(f"第 {line_number} 行 {field} 不是数字: {raw!r}") from error


def _parse_optional_float(raw: str | None, field: str, line_number: int) -> float | None:
    cleaned = _clean(raw)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError as error:
        raise SourceError(f"第 {line_number} 行 {field} 不是数字: {raw!r}") from error


def parse_airports(text: str) -> list[AirportRecord]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as error:
        raise SourceError("CSV 为空") from error
    header = [column.strip() for column in header]
    # 列顺序在数据字典页与真实 CSV 之间并不一致（icao_code/iata_code/gps_code），
    # 因此按列名集合校验、按列名取值，只对缺列/多列/重复列报警。
    if len(set(header)) != len(header):
        raise SourceError(f"CSV 表头存在重复列: {header}")
    missing = [column for column in SOURCE_COLUMNS if column not in set(header)]
    extra = [column for column in header if column not in set(SOURCE_COLUMNS)]
    if missing or extra:
        raise SourceError(
            "CSV 表头与 OurAirports 数据字典不一致："
            f"缺少 {missing}，多出 {extra}（实际列顺序 {header}）"
        )

    records: list[AirportRecord] = []
    seen_ids: dict[int, int] = {}
    seen_idents: dict[str, int] = {}
    for line_number, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            raise SourceError(
                f"第 {line_number} 行有 {len(row)} 列，期望 {len(header)} 列"
            )
        raw = dict(zip(header, row))
        record = _build_record(raw, line_number)
        if record.id in seen_ids:
            raise SourceError(f"第 {line_number} 行 id={record.id} 与第 {seen_ids[record.id]} 行重复")
        if record.ident in seen_idents:
            raise SourceError(
                f"第 {line_number} 行 ident={record.ident} 与第 {seen_idents[record.ident]} 行重复"
            )
        seen_ids[record.id] = line_number
        seen_idents[record.ident] = line_number
        records.append(record)
    if not records:
        raise SourceError("CSV 没有数据行")
    return records


def _build_record(raw: dict[str, str], line_number: int) -> AirportRecord:
    ident = _clean(raw["ident"])
    name = _clean(raw["name"])
    type_value = _clean(raw["type"])
    if not ident:
        raise SourceError(f"第 {line_number} 行 ident 为空")
    if not name:
        raise SourceError(f"第 {line_number} 行 name 为空")
    if type_value not in ALLOWED_TYPES:
        raise SourceError(f"第 {line_number} 行 type={type_value!r} 不在允许取值内")
    continent = _clean(raw["continent"])
    if continent is not None and continent not in ALLOWED_CONTINENTS:
        raise SourceError(f"第 {line_number} 行 continent={continent!r} 不在允许取值内")
    scheduled_service = _clean(raw["scheduled_service"])
    if scheduled_service is not None and scheduled_service not in ALLOWED_SCHEDULED_SERVICE:
        raise SourceError(
            f"第 {line_number} 行 scheduled_service={scheduled_service!r} 不是 yes/no"
        )
    return AirportRecord(
        id=_parse_int(raw["id"].strip(), "id", line_number),
        ident=ident,
        type=type_value,
        name=name,
        latitude_deg=_parse_optional_float(raw["latitude_deg"], "latitude_deg", line_number),
        longitude_deg=_parse_optional_float(raw["longitude_deg"], "longitude_deg", line_number),
        elevation_ft=_parse_optional_int(raw["elevation_ft"], "elevation_ft", line_number),
        continent=continent,
        iso_country=_clean(raw["iso_country"]),
        iso_region=_clean(raw["iso_region"]),
        municipality=_clean(raw["municipality"]),
        scheduled_service=scheduled_service,
        gps_code=_clean(raw["gps_code"]),
        icao_code=_clean(raw["icao_code"]),
        iata_code=_clean(raw["iata_code"]),
        local_code=_clean(raw["local_code"]),
        home_link=_clean(raw["home_link"]),
        wikipedia_link=_clean(raw["wikipedia_link"]),
        keywords=_clean(raw["keywords"]),
    )


def sanity_check(
    records: list[AirportRecord],
    *,
    min_rows: int = MIN_EXPECTED_ROWS,
    min_large_airports: int = MIN_EXPECTED_LARGE_AIRPORTS,
) -> None:
    """防止把截断或异常的文件写进正式表。阈值可在测试或试跑时放宽。"""
    if len(records) < min_rows:
        raise SourceError(f"只有 {len(records)} 行，低于安全下限 {min_rows}")
    large = sum(1 for record in records if record.type == "large_airport")
    if large < min_large_airports:
        raise SourceError(f"large_airport 只有 {large} 条，低于安全下限 {min_large_airports}")


def batched(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
