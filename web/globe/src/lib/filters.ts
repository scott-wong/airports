import {
  AIRPORT_TYPES,
  type Airport,
  type AirportType,
  type BasemapStyle,
  type FilterState,
} from "../types";

export const DEFAULT_FILTERS: FilterState = {
  types: ["large_airport", "medium_airport", "seaplane_base", "balloonport"],
  countries: [],
  query: "",
  hasZh: false,
  scheduledOnly: false,
  borders: true,
  basemap: "satellite",
};

const BASEMAPS: BasemapStyle[] = ["satellite", "street", "wireframe"];

export function haystackOf(airport: Airport): string {
  if (!airport.keywords) return buildHaystack(airport);
  return buildHaystack(airport);
}

function buildHaystack(airport: Airport): string {
  return [
    airport.name,
    airport.name_zh,
    airport.ident,
    airport.iata_code,
    airport.icao_code,
    airport.gps_code,
    airport.local_code,
    airport.municipality,
    airport.municipality_zh,
    airport.location_zh,
    airport.keywords,
    airport.iso_country,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function matchesFilters(airport: Airport, filters: FilterState, haystack?: string): boolean {
  if (!filters.types.includes(airport.type)) return false;
  if (filters.countries.length > 0 && !filters.countries.includes(airport.iso_country ?? "")) {
    return false;
  }
  if (filters.hasZh && !airport.name_zh) return false;
  if (filters.scheduledOnly && airport.scheduled_service !== "yes") return false;
  const query = filters.query.trim().toLowerCase();
  if (query) {
    const text = haystack ?? buildHaystack(airport);
    for (const token of query.split(/\s+/)) {
      if (!text.includes(token)) return false;
    }
  }
  return true;
}

export function applyFilters(airports: Airport[], filters: FilterState): Airport[] {
  return airports.filter((airport) => matchesFilters(airport, filters));
}

export function countByType(airports: Airport[]): Record<AirportType, number> {
  const counts = Object.fromEntries(AIRPORT_TYPES.map((type) => [type, 0])) as Record<
    AirportType,
    number
  >;
  for (const airport of airports) {
    counts[airport.type] += 1;
  }
  return counts;
}

export function countryCounts(airports: Airport[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const airport of airports) {
    const code = airport.iso_country;
    if (!code) continue;
    counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  return counts;
}

export function encodeFilters(filters: FilterState): string {
  const params = new URLSearchParams();
  params.set("type", filters.types.join(","));
  if (filters.countries.length) params.set("country", filters.countries.join(","));
  if (filters.query) params.set("q", filters.query);
  if (filters.hasZh) params.set("zh", "1");
  if (filters.scheduledOnly) params.set("sched", "1");
  if (!filters.borders) params.set("borders", "0");
  if (filters.basemap !== "satellite") params.set("map", filters.basemap);
  return params.toString();
}

export function decodeFilters(search: string): FilterState {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const types = (params.get("type") ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter((value): value is AirportType => (AIRPORT_TYPES as readonly string[]).includes(value));
  return {
    types: params.has("type") ? types : DEFAULT_FILTERS.types,
    countries: (params.get("country") ?? "")
      .split(",")
      .map((value) => value.trim().toUpperCase())
      .filter((value) => /^[A-Z0-9]{2}$/.test(value)),
    query: params.get("q") ?? "",
    hasZh: params.get("zh") === "1",
    scheduledOnly: params.get("sched") === "1",
    borders: params.get("borders") !== "0",
    basemap: (BASEMAPS as string[]).includes(params.get("map") ?? "")
      ? (params.get("map") as BasemapStyle)
      : "satellite",
  };
}
