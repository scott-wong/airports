import { AIRPORT_TYPES, type Airport, type AirportSnapshot, type AirportType } from "../types";

const TYPE_SET = new Set<string>(AIRPORT_TYPES);

export function isAirportType(value: unknown): value is AirportType {
  return typeof value === "string" && TYPE_SET.has(value);
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * 解析 export-web 生成的快照：数组行 + fields 字段表。
 * 缺字段用 null 兜底，坐标缺失或类型未知的行直接跳过（不让脏数据进渲染层）。
 */
export function parseSnapshot(raw: unknown): AirportSnapshot {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("snapshot: 不是对象");
  }
  const data = raw as Record<string, unknown>;
  const schemaVersion = asNumber(data.schemaVersion);
  if (schemaVersion !== 1) {
    throw new Error(`snapshot: 不支持的 schemaVersion=${String(data.schemaVersion)}`);
  }
  const fields = data.fields;
  const rows = data.rows;
  if (!Array.isArray(fields) || !Array.isArray(rows)) {
    throw new Error("snapshot: 缺少 fields/rows");
  }
  const index = new Map<string, number>(fields.map((name, position) => [String(name), position]));
  const required = ["id", "ident", "type", "name", "latitude_deg", "longitude_deg"];
  for (const name of required) {
    if (!index.has(name)) {
      throw new Error(`snapshot: 字段表缺少 ${name}`);
    }
  }

  const pick = (row: unknown[], name: string): unknown =>
    index.has(name) ? row[index.get(name) as number] : undefined;

  const airports: Airport[] = [];
  for (const row of rows) {
    if (!Array.isArray(row)) continue;
    const type = pick(row, "type");
    const lat = asNumber(pick(row, "latitude_deg"));
    const lon = asNumber(pick(row, "longitude_deg"));
    const id = asNumber(pick(row, "id"));
    const ident = asString(pick(row, "ident"));
    const name = asString(pick(row, "name"));
    if (!isAirportType(type) || lat === null || lon === null || id === null || !ident || !name) {
      continue;
    }
    airports.push({
      id,
      ident,
      type,
      name,
      lat,
      lon,
      elevation_ft: asNumber(pick(row, "elevation_ft")),
      continent: asString(pick(row, "continent")),
      iso_country: asString(pick(row, "iso_country")),
      iso_region: asString(pick(row, "iso_region")),
      municipality: asString(pick(row, "municipality")),
      scheduled_service: asString(pick(row, "scheduled_service")),
      gps_code: asString(pick(row, "gps_code")),
      icao_code: asString(pick(row, "icao_code")),
      iata_code: asString(pick(row, "iata_code")),
      local_code: asString(pick(row, "local_code")),
      home_link: asString(pick(row, "home_link")),
      wikipedia_link: asString(pick(row, "wikipedia_link")),
      keywords: asString(pick(row, "keywords")),
      name_zh: asString(pick(row, "name_zh")),
      name_zh_source: asString(pick(row, "name_zh_source")),
      municipality_zh: asString(pick(row, "municipality_zh")),
      municipality_zh_source: asString(pick(row, "municipality_zh_source")),
      location_zh: asString(pick(row, "location_zh")),
      location_zh_source: asString(pick(row, "location_zh_source")),
    });
  }

  return {
    schemaVersion,
    generatedAt: asString(data.generatedAt) ?? "",
    source: (data.source as AirportSnapshot["source"]) ?? { url: "", sha256: "", rowCount: airports.length },
    names: (data.names as AirportSnapshot["names"]) ?? { file: "", sha256: "", rowCount: 0 },
    airports,
  };
}

export const SNAPSHOT_URL = `${import.meta.env.BASE_URL}airports.json.gz`;

export async function fetchSnapshot(url = SNAPSHOT_URL): Promise<AirportSnapshot> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`快照加载失败：HTTP ${response.status}`);
  }
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const isGzip = bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
  const text = isGzip
    ? await new Response(
        new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip")),
      ).text()
    : new TextDecoder().decode(bytes);
  return parseSnapshot(JSON.parse(text));
}
