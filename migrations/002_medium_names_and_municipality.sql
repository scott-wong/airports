-- 扩大中文名覆盖到 medium_airport，并开始填充 municipality_zh。
-- 中文名的来源链路变粗，因此记录来源 provenance，并把 collector_run 的列名改成中性名称。

ALTER TABLE airports.airport ADD COLUMN IF NOT EXISTS municipality_zh_source text;
ALTER TABLE airports.airport_staging ADD COLUMN IF NOT EXISTS municipality_zh_source text;

ALTER TABLE airports.collector_run RENAME COLUMN rows_large_airport TO rows_named_airports;
ALTER TABLE airports.collector_run RENAME COLUMN rows_large_airport_missing_zh TO rows_missing_zh;

CREATE OR REPLACE VIEW airports.airport_active AS
SELECT
    id, ident, type, name, latitude_deg, longitude_deg, elevation_ft,
    continent, iso_country, iso_region, municipality, scheduled_service,
    gps_code, icao_code, iata_code, local_code, home_link, wikipedia_link, keywords,
    name_zh, municipality_zh, name_zh_source, name_zh_updated_at,
    first_seen_at, last_seen_at, updated_at, source_snapshot_at,
    municipality_zh_source
FROM airports.airport
WHERE is_active;
