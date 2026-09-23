-- 拆开两个概念：
--   municipality_zh = 机场服务的城市（按 OurAirports municipality 字段匹配到的居民点）
--   location_zh     = 机场所在的居民点（Wikidata P131 中的人类聚居地，按人口取最大）
-- 设计上曾把 P131 直接写进 municipality_zh（北京大兴 → 九州镇），语义错位，故拆成两列。

ALTER TABLE airports.airport ADD COLUMN IF NOT EXISTS location_zh text;
ALTER TABLE airports.airport ADD COLUMN IF NOT EXISTS location_zh_source text;
ALTER TABLE airports.airport_staging ADD COLUMN IF NOT EXISTS location_zh text;
ALTER TABLE airports.airport_staging ADD COLUMN IF NOT EXISTS location_zh_source text;

CREATE OR REPLACE VIEW airports.airport_active AS
SELECT
    id, ident, type, name, latitude_deg, longitude_deg, elevation_ft,
    continent, iso_country, iso_region, municipality, scheduled_service,
    gps_code, icao_code, iata_code, local_code, home_link, wikipedia_link, keywords,
    name_zh, municipality_zh, name_zh_source, name_zh_updated_at,
    first_seen_at, last_seen_at, updated_at, source_snapshot_at,
    municipality_zh_source,
    location_zh, location_zh_source
FROM airports.airport
WHERE is_active;
