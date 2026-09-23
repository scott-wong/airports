-- OurAirports 机场参考数据：独立 schema。
-- 上游字段（19 列）名称与语义严格照 https://ourairports.com/help/data-dictionary.html ，
-- 例外列见 CONTEXT.md 与 README。注意：字典写 type 允许 closed_airport，实际数据为 closed。

CREATE SCHEMA IF NOT EXISTS airports;

CREATE TABLE IF NOT EXISTS airports.schema_migrations (
    version text PRIMARY KEY,
    filename text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS airports.airport (
    id bigint PRIMARY KEY,
    ident text NOT NULL,
    type text NOT NULL CHECK (type IN (
        'balloonport', 'closed', 'heliport', 'large_airport',
        'medium_airport', 'seaplane_base', 'small_airport'
    )),
    name text NOT NULL,
    latitude_deg double precision,
    longitude_deg double precision,
    elevation_ft integer,
    continent text CHECK (continent IN ('AF', 'AN', 'AS', 'EU', 'NA', 'OC', 'SA')),
    iso_country text,
    iso_region text,
    municipality text,
    scheduled_service text CHECK (scheduled_service IN ('yes', 'no')),
    gps_code text,
    icao_code text,
    iata_code text,
    local_code text,
    home_link text,
    wikipedia_link text,
    keywords text,
    name_zh text,
    municipality_zh text,
    name_zh_source text,
    name_zh_updated_at timestamptz,
    row_hash text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    deactivated_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    source_snapshot_at timestamptz NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS airport_ident_key ON airports.airport (ident);
CREATE INDEX IF NOT EXISTS airport_iata_code_idx ON airports.airport (iata_code);
CREATE INDEX IF NOT EXISTS airport_icao_code_idx ON airports.airport (icao_code);
CREATE INDEX IF NOT EXISTS airport_type_idx ON airports.airport (type);
CREATE INDEX IF NOT EXISTS airport_iso_country_idx ON airports.airport (iso_country);
CREATE INDEX IF NOT EXISTS airport_municipality_idx ON airports.airport (municipality);
CREATE INDEX IF NOT EXISTS airport_active_idx ON airports.airport (id) WHERE is_active;

-- 每轮采集先落到 staging，校验通过后再一次性合并，避免半截数据进入正式表。
CREATE TABLE IF NOT EXISTS airports.airport_staging (
    run_id bigint NOT NULL,
    id bigint NOT NULL,
    ident text NOT NULL,
    type text NOT NULL,
    name text NOT NULL,
    latitude_deg double precision,
    longitude_deg double precision,
    elevation_ft integer,
    continent text,
    iso_country text,
    iso_region text,
    municipality text,
    scheduled_service text,
    gps_code text,
    icao_code text,
    iata_code text,
    local_code text,
    home_link text,
    wikipedia_link text,
    keywords text,
    name_zh text,
    municipality_zh text,
    name_zh_source text,
    row_hash text NOT NULL,
    source_snapshot_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS airport_staging_run_idx ON airports.airport_staging (run_id);

CREATE TABLE IF NOT EXISTS airports.collector_run (
    run_id bigserial PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    source_url text NOT NULL,
    source_etag text,
    source_last_modified text,
    source_sha256 text,
    source_bytes bigint,
    names_file_sha256 text,
    rows_total integer,
    rows_inserted integer,
    rows_updated integer,
    rows_unchanged integer,
    rows_reactivated integer,
    rows_deactivated integer,
    rows_large_airport integer,
    rows_large_airport_missing_zh integer,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error_message text
);

CREATE INDEX IF NOT EXISTS collector_run_started_idx ON airports.collector_run (started_at DESC);

-- is_active 与 type='closed' 是两个独立维度：视图只过滤失活，不过滤 closed。
CREATE OR REPLACE VIEW airports.airport_active AS
SELECT
    id, ident, type, name, latitude_deg, longitude_deg, elevation_ft,
    continent, iso_country, iso_region, municipality, scheduled_service,
    gps_code, icao_code, iata_code, local_code, home_link, wikipedia_link, keywords,
    name_zh, municipality_zh, name_zh_source, name_zh_updated_at,
    first_seen_at, last_seen_at, updated_at, source_snapshot_at
FROM airports.airport
WHERE is_active;

-- 只读账号可读；写权限仅 project_admin。PostgREST 暴露 airports schema 另见 ops/。
GRANT USAGE ON SCHEMA airports TO anon, authenticated;
GRANT SELECT ON airports.airport TO anon, authenticated;
GRANT SELECT ON airports.airport_active TO anon, authenticated;
