from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import httpx

from .source import (
    MIN_EXPECTED_LARGE_AIRPORTS,
    MIN_EXPECTED_ROWS,
    AirportRecord,
    download_airports,
    parse_airports,
    sanity_check,
)
from .storage.repository import AirportRepository, MergeStats, utc_now
from .zh_names import NameEntry, ZhNamesError, file_sha256, load_names

ProgressFn = Callable[[str], None]


class CollectError(RuntimeError):
    """采集流程失败。"""


@dataclass
class CollectResult:
    run_id: int
    snapshot_at: datetime
    source_sha256: str
    source_bytes: int
    rows_total: int
    rows_large_airport: int
    rows_large_airport_missing_zh: int
    merge: MergeStats
    rows_deactivated: int
    names_file_sha256: str | None

    def summary(self) -> str:
        return (
            f"run {self.run_id}: 共 {self.rows_total} 行，新增 {self.merge.inserted}，"
            f"更新 {self.merge.updated}，未变 {self.merge.unchanged}，"
            f"复活 {self.merge.reactivated}，失活 {self.rows_deactivated}；"
            f"大机场 {self.rows_large_airport} 条，其中缺中文名 {self.rows_large_airport_missing_zh} 条"
        )


def build_staging_rows(
    records: list[AirportRecord], names: dict[int, NameEntry]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        entry = names.get(record.id)
        rows.append(
            {
                "id": record.id,
                "ident": record.ident,
                "type": record.type,
                "name": record.name,
                "latitude_deg": record.latitude_deg,
                "longitude_deg": record.longitude_deg,
                "elevation_ft": record.elevation_ft,
                "continent": record.continent,
                "iso_country": record.iso_country,
                "iso_region": record.iso_region,
                "municipality": record.municipality,
                "scheduled_service": record.scheduled_service,
                "gps_code": record.gps_code,
                "icao_code": record.icao_code,
                "iata_code": record.iata_code,
                "local_code": record.local_code,
                "home_link": record.home_link,
                "wikipedia_link": record.wikipedia_link,
                "keywords": record.keywords,
                "name_zh": entry.name_zh if entry else None,
                "municipality_zh": entry.municipality_zh if entry else None,
                "name_zh_source": entry.name_zh_source if entry else None,
                "row_hash": record.row_hash,
            }
        )
    return rows


def load_records(
    *,
    csv_path: Path | None,
    http_client: httpx.Client,
    source_url: str,
    on_progress: ProgressFn | None = None,
) -> tuple[list[AirportRecord], Any]:
    """返回 (记录列表, 下载结果或 None)。"""
    if csv_path is not None:
        if on_progress:
            on_progress(f"读取本地 CSV {csv_path}")
        text = Path(csv_path).read_text(encoding="utf-8")
        return parse_airports(text), None
    if on_progress:
        on_progress(f"下载 {source_url}")
    download = download_airports(source_url, http_client)
    if on_progress:
        on_progress(f"下载完成 {len(download.content) / 1024 / 1024:.1f} MB，sha256 {download.sha256[:12]}…")
    return parse_airports(download.content.decode("utf-8-sig")), download


def collect(
    repository: AirportRepository,
    http_client: httpx.Client,
    *,
    source_url: str,
    names_path: Path,
    csv_path: Path | None = None,
    allow_missing_names: bool = False,
    on_progress: ProgressFn | None = None,
    min_rows: int = MIN_EXPECTED_ROWS,
    min_large_airports: int = MIN_EXPECTED_LARGE_AIRPORTS,
) -> CollectResult:
    def progress(message: str) -> None:
        if on_progress:
            on_progress(message)

    records, download = load_records(
        csv_path=csv_path, http_client=http_client, source_url=source_url, on_progress=on_progress
    )
    progress(f"解析 {len(records)} 行")
    sanity_check(records, min_rows=min_rows, min_large_airports=min_large_airports)

    names: dict[int, NameEntry] = {}
    names_digest: str | None = None
    if Path(names_path).exists():
        names = load_names(Path(names_path))
        names_digest = file_sha256(Path(names_path))
        progress(f"载入中文名 {len(names)} 条（sha256 {names_digest[:12]}…）")
    elif not allow_missing_names:
        raise ZhNamesError(
            f"中文名文件不存在: {names_path}；先运行 `airports-collector names refresh`，"
            "或显式传入 --allow-missing-names"
        )
    if not names and not allow_missing_names:
        raise ZhNamesError(f"中文名文件 {names_path} 没有任何记录")

    large_airports = [record for record in records if record.type == "large_airport"]
    missing_zh = [record for record in large_airports if not (names.get(record.id) and names[record.id].name_zh)]
    if missing_zh and not allow_missing_names:
        progress(f"注意：{len(missing_zh)} 条大机场没有中文名（unresolved）")

    rows = build_staging_rows(records, names)
    snapshot_at = utc_now()

    run_id = repository.start_run(source_url, names_digest)
    try:
        repository.clear_staging(run_id)
        staged = 0
        for chunk in repository.chunks(rows):
            staged += repository.stage_rows(run_id, snapshot_at, chunk)
            progress(f"  已写入 staging {staged}/{len(rows)}")
        merge = repository.merge(run_id)
        deactivated = repository.deactivate_missing(snapshot_at)
        repository.clear_staging(run_id)
        repository.finish_run(
            run_id,
            etag=download.etag if download else None,
            last_modified=download.last_modified if download else None,
            source_sha256=download.sha256 if download else None,
            source_bytes=len(download.content) if download else None,
            rows_total=len(rows),
            rows_inserted=merge.inserted,
            rows_updated=merge.updated,
            rows_unchanged=merge.unchanged,
            rows_reactivated=merge.reactivated,
            rows_deactivated=deactivated,
            rows_large_airport=len(large_airports),
            rows_large_airport_missing_zh=len(missing_zh),
        )
    except Exception as error:
        try:
            repository.fail_run(run_id, f"{type(error).__name__}: {error}")
        except Exception:  # pragma: no cover - 失败上报不应掩盖原始错误
            pass
        raise

    return CollectResult(
        run_id=run_id,
        snapshot_at=snapshot_at,
        source_sha256=download.sha256 if download else "",
        source_bytes=len(download.content) if download else 0,
        rows_total=len(rows),
        rows_large_airport=len(large_airports),
        rows_large_airport_missing_zh=len(missing_zh),
        merge=merge,
        rows_deactivated=deactivated,
        names_file_sha256=names_digest,
    )
