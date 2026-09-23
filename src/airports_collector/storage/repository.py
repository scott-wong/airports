from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .clients import StorageClient

SCHEMA = "airports"

STAGING_INSERT = f"""
INSERT INTO {SCHEMA}.airport_staging (
    run_id, source_snapshot_at, id, ident, type, name, latitude_deg, longitude_deg,
    elevation_ft, continent, iso_country, iso_region, municipality, scheduled_service,
    gps_code, icao_code, iata_code, local_code, home_link, wikipedia_link, keywords,
    name_zh, municipality_zh, name_zh_source, row_hash
)
SELECT
    $1::bigint, $2::timestamptz, t.id, t.ident, t.type, t.name, t.latitude_deg, t.longitude_deg,
    t.elevation_ft, t.continent, t.iso_country, t.iso_region, t.municipality, t.scheduled_service,
    t.gps_code, t.icao_code, t.iata_code, t.local_code, t.home_link, t.wikipedia_link, t.keywords,
    t.name_zh, t.municipality_zh, t.name_zh_source, t.row_hash
FROM jsonb_to_recordset($3::jsonb) AS t(
    id bigint, ident text, type text, name text, latitude_deg double precision,
    longitude_deg double precision, elevation_ft integer, continent text, iso_country text,
    iso_region text, municipality text, scheduled_service text, gps_code text, icao_code text,
    iata_code text, local_code text, home_link text, wikipedia_link text, keywords text,
    name_zh text, municipality_zh text, name_zh_source text, row_hash text
)
"""

MERGE = f"""
WITH input AS (
    SELECT * FROM {SCHEMA}.airport_staging WHERE run_id = $1::bigint
), existing AS (
    SELECT a.id, a.row_hash, a.is_active, a.name_zh
    FROM {SCHEMA}.airport a
    JOIN input i ON i.id = a.id
), upserted AS (
    INSERT INTO {SCHEMA}.airport AS a (
        id, ident, type, name, latitude_deg, longitude_deg, elevation_ft, continent,
        iso_country, iso_region, municipality, scheduled_service, gps_code, icao_code,
        iata_code, local_code, home_link, wikipedia_link, keywords, name_zh, municipality_zh,
        name_zh_source, name_zh_updated_at, row_hash, is_active, first_seen_at, last_seen_at,
        deactivated_at, updated_at, source_snapshot_at
    )
    SELECT
        i.id, i.ident, i.type, i.name, i.latitude_deg, i.longitude_deg, i.elevation_ft, i.continent,
        i.iso_country, i.iso_region, i.municipality, i.scheduled_service, i.gps_code, i.icao_code,
        i.iata_code, i.local_code, i.home_link, i.wikipedia_link, i.keywords, i.name_zh,
        i.municipality_zh, i.name_zh_source,
        CASE WHEN i.name_zh IS NULL THEN NULL ELSE i.source_snapshot_at END,
        i.row_hash, true, i.source_snapshot_at, i.source_snapshot_at, NULL, i.source_snapshot_at,
        i.source_snapshot_at
    FROM input i
    ON CONFLICT (id) DO UPDATE SET
        ident = EXCLUDED.ident,
        type = EXCLUDED.type,
        name = EXCLUDED.name,
        latitude_deg = EXCLUDED.latitude_deg,
        longitude_deg = EXCLUDED.longitude_deg,
        elevation_ft = EXCLUDED.elevation_ft,
        continent = EXCLUDED.continent,
        iso_country = EXCLUDED.iso_country,
        iso_region = EXCLUDED.iso_region,
        municipality = EXCLUDED.municipality,
        scheduled_service = EXCLUDED.scheduled_service,
        gps_code = EXCLUDED.gps_code,
        icao_code = EXCLUDED.icao_code,
        iata_code = EXCLUDED.iata_code,
        local_code = EXCLUDED.local_code,
        home_link = EXCLUDED.home_link,
        wikipedia_link = EXCLUDED.wikipedia_link,
        keywords = EXCLUDED.keywords,
        name_zh = EXCLUDED.name_zh,
        municipality_zh = EXCLUDED.municipality_zh,
        name_zh_source = EXCLUDED.name_zh_source,
        name_zh_updated_at = CASE
            WHEN a.name_zh IS DISTINCT FROM EXCLUDED.name_zh THEN EXCLUDED.source_snapshot_at
            ELSE a.name_zh_updated_at
        END,
        row_hash = EXCLUDED.row_hash,
        is_active = true,
        deactivated_at = NULL,
        last_seen_at = EXCLUDED.last_seen_at,
        updated_at = CASE
            WHEN a.row_hash IS DISTINCT FROM EXCLUDED.row_hash
              OR a.name_zh IS DISTINCT FROM EXCLUDED.name_zh
              OR a.is_active = false
            THEN EXCLUDED.source_snapshot_at
            ELSE a.updated_at
        END,
        source_snapshot_at = EXCLUDED.source_snapshot_at
    RETURNING a.id AS id
)
SELECT
    count(*) FILTER (WHERE e.id IS NULL) AS inserted,
    count(*) FILTER (WHERE e.id IS NOT NULL AND e.row_hash IS DISTINCT FROM i.row_hash) AS updated,
    count(*) FILTER (WHERE e.id IS NOT NULL AND e.row_hash IS NOT DISTINCT FROM i.row_hash) AS unchanged,
    count(*) FILTER (WHERE e.id IS NOT NULL AND e.is_active = false) AS reactivated
FROM upserted u
JOIN input i ON i.id = u.id
LEFT JOIN existing e ON e.id = u.id
"""

DEACTIVATE = f"""
UPDATE {SCHEMA}.airport
SET is_active = false,
    deactivated_at = $2::timestamptz,
    updated_at = $2::timestamptz
WHERE is_active AND source_snapshot_at < $1::timestamptz
RETURNING id
"""

DELETE_STAGING = f"DELETE FROM {SCHEMA}.airport_staging WHERE run_id = $1::bigint"

RUN_START = f"""
INSERT INTO {SCHEMA}.collector_run (status, source_url, names_file_sha256, started_at)
VALUES ('running', $1, $2, now())
RETURNING run_id
"""

RUN_FINISH = f"""
UPDATE {SCHEMA}.collector_run
SET status = $2,
    finished_at = now(),
    source_etag = $3,
    source_last_modified = $4,
    source_sha256 = $5,
    source_bytes = $6,
    rows_total = $7,
    rows_inserted = $8,
    rows_updated = $9,
    rows_unchanged = $10,
    rows_reactivated = $11,
    rows_deactivated = $12,
    rows_large_airport = $13,
    rows_large_airport_missing_zh = $14,
    error_message = $15
WHERE run_id = $1::bigint
"""

RUN_FAIL = f"""
UPDATE {SCHEMA}.collector_run
SET status = 'failed', finished_at = now(), error_message = $2
WHERE run_id = $1::bigint
"""

STATS = f"""
SELECT
    (SELECT count(*) FROM {SCHEMA}.airport) AS rows_total,
    (SELECT count(*) FROM {SCHEMA}.airport WHERE is_active) AS rows_active,
    (SELECT count(*) FROM {SCHEMA}.airport WHERE NOT is_active) AS rows_inactive,
    (SELECT count(*) FROM {SCHEMA}.airport WHERE is_active AND type = 'large_airport') AS large_airports,
    (SELECT count(*) FROM {SCHEMA}.airport
      WHERE is_active AND type = 'large_airport' AND name_zh IS NOT NULL) AS large_airports_with_zh,
    (SELECT count(*) FROM {SCHEMA}.airport WHERE name_zh IS NOT NULL) AS rows_with_zh,
    (SELECT max(finished_at) FROM {SCHEMA}.collector_run WHERE status = 'succeeded') AS last_success_at,
    (SELECT run_id FROM {SCHEMA}.collector_run ORDER BY run_id DESC LIMIT 1) AS last_run_id,
    (SELECT status FROM {SCHEMA}.collector_run ORDER BY run_id DESC LIMIT 1) AS last_run_status
"""


@dataclass(frozen=True)
class MergeStats:
    inserted: int
    updated: int
    unchanged: int
    reactivated: int
    deactivated: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_int(value: Any) -> int:
    return int(value or 0)


class AirportRepository:
    def __init__(self, storage: StorageClient, batch_size: int = 1000) -> None:
        self.storage = storage
        self.batch_size = batch_size

    def start_run(self, source_url: str, names_file_sha256: str | None) -> int:
        rows = self.storage.execute(RUN_START, (source_url, names_file_sha256))
        if not rows:
            raise RuntimeError("创建 collector_run 失败")
        return int(rows[0]["run_id"])

    def clear_staging(self, run_id: int) -> None:
        self.storage.execute(DELETE_STAGING, (run_id,))

    def stage_rows(self, run_id: int, snapshot_at: datetime, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.storage.execute(
            STAGING_INSERT,
            (run_id, snapshot_at.isoformat(), json.dumps(rows, ensure_ascii=False)),
        )
        return len(rows)

    def merge(self, run_id: int) -> MergeStats:
        rows = self.storage.execute(MERGE, (run_id,))
        if not rows:
            raise RuntimeError("合并语句没有返回统计行")
        row = rows[0]
        return MergeStats(
            inserted=_as_int(row["inserted"]),
            updated=_as_int(row["updated"]),
            unchanged=_as_int(row["unchanged"]),
            reactivated=_as_int(row["reactivated"]),
            deactivated=0,
        )

    def deactivate_missing(self, snapshot_at: datetime) -> int:
        rows = self.storage.execute(DEACTIVATE, (snapshot_at.isoformat(), snapshot_at.isoformat()))
        return len(rows)

    def finish_run(
        self,
        run_id: int,
        *,
        etag: str | None,
        last_modified: str | None,
        source_sha256: str | None,
        source_bytes: int | None,
        rows_total: int | None,
        rows_inserted: int | None,
        rows_updated: int | None,
        rows_unchanged: int | None,
        rows_reactivated: int | None,
        rows_deactivated: int | None,
        rows_large_airport: int | None,
        rows_large_airport_missing_zh: int | None,
    ) -> None:
        self.storage.execute(
            RUN_FINISH,
            (
                run_id,
                "succeeded",
                etag,
                last_modified,
                source_sha256,
                source_bytes,
                rows_total,
                rows_inserted,
                rows_updated,
                rows_unchanged,
                rows_reactivated,
                rows_deactivated,
                rows_large_airport,
                rows_large_airport_missing_zh,
                None,
            ),
        )

    def fail_run(self, run_id: int, message: str) -> None:
        self.storage.execute(RUN_FAIL, (run_id, message[:2000]))

    def stats(self) -> dict[str, Any]:
        rows = self.storage.query(STATS)
        return rows[0] if rows else {}

    def chunks(self, rows: list[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
        for start in range(0, len(rows), self.batch_size):
            yield rows[start : start + self.batch_size]
