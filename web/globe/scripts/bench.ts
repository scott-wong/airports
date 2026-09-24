/**
 * 本地性能基准（不进 CI，见 web/globe/docs/adr/0002 与 README）：
 *   bun run bench
 * 用 8.6 万条合成数据测快照解析、筛选、几何构建与拾取的耗时。
 */
import { applyFilters, DEFAULT_FILTERS, haystackOf } from "../src/lib/filters";
import { buildGeometry } from "../src/lib/points";
import { buildPickGrid, candidatesNear, pickNearest } from "../src/lib/picking";
import { parseSnapshot } from "../src/lib/snapshot";
import { AIRPORT_TYPES, type Airport } from "../src/types";

const COUNT = 86126;
const TYPES = AIRPORT_TYPES;

function makeAirports(count: number): Airport[] {
  const airports: Airport[] = new Array(count);
  for (let index = 0; index < count; index += 1) {
    const lat = (Math.asin((2 * ((index * 2654435761) % 100000)) / 100000 - 1) * 180) / Math.PI;
    const lon = ((index * 40503) % 360000) / 1000 - 180;
    const type = TYPES[index % TYPES.length];
    airports[index] = {
      id: index + 1,
      ident: `X${index}`,
      type,
      name: `Airport number ${index}`,
      lat,
      lon,
      elevation_ft: (index % 9000) - 100,
      continent: "AS",
      iso_country: `C${index % 200}`,
      iso_region: "R",
      municipality: `City ${index % 5000}`,
      scheduled_service: index % 3 === 0 ? "yes" : "no",
      gps_code: null,
      icao_code: `X${index}`,
      iata_code: null,
      local_code: null,
      home_link: null,
      wikipedia_link: null,
      keywords: index % 10 === 0 ? "keyword 北京" : null,
      name_zh: index % 5 === 0 ? `机场${index}` : null,
      name_zh_source: index % 5 === 0 ? "wikidata:Q1:zh-cn" : null,
      municipality_zh: index % 5 === 0 ? `城市${index}` : null,
      municipality_zh_source: null,
      location_zh: null,
      location_zh_source: null,
    };
  }
  return airports;
}

function time(label: string, fn: () => void): number {
  const start = performance.now();
  fn();
  const elapsed = performance.now() - start;
  console.log(`${label.padEnd(34)} ${elapsed.toFixed(1)} ms`);
  return elapsed;
}

const airports = makeAirports(COUNT);
console.log(`synthetic airports: ${COUNT}\n`);

let filtered: Airport[] = [];
time("build geometry (all 86k)", () => {
  buildGeometry(airports);
});
time("default filter (types only)", () => {
  filtered = applyFilters(airports, DEFAULT_FILTERS);
});
time("filter + query (all types)", () => {
  applyFilters(airports, { ...DEFAULT_FILTERS, types: [...TYPES], query: "北京" });
});
time("haystack build (86k)", () => {
  for (const airport of airports) haystackOf(airport);
});

const grid = buildPickGrid(filtered);
time("build pick grid", () => {
  buildPickGrid(filtered);
});

const project = (airport: Airport) => ({ x: airport.lon * 4, y: airport.lat * 4 });
time("1000 hover picks", () => {
  for (let index = 0; index < 1000; index += 1) {
    const target = filtered[(index * 97) % filtered.length];
    if (!target) continue;
    const cursor = project(target);
    const candidates = candidatesNear(grid, target.lat, target.lon, 1);
    pickNearest(candidates, filtered, project, cursor, 12);
  }
});

const snapshotRows = airports.map((airport) => [
  airport.id,
  airport.ident,
  airport.type,
  airport.name,
  airport.lat,
  airport.lon,
  airport.name_zh,
  airport.name_zh_source,
]);
const payload = JSON.stringify({
  schemaVersion: 1,
  fields: ["id", "ident", "type", "name", "latitude_deg", "longitude_deg", "name_zh", "name_zh_source"],
  rows: snapshotRows,
});
console.log(`\nsnapshot payload: ${(payload.length / 1048576).toFixed(1)} MB`);
time("JSON.parse + parseSnapshot", () => {
  parseSnapshot(JSON.parse(payload));
});
