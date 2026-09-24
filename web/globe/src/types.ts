export const AIRPORT_TYPES = [
  "large_airport",
  "medium_airport",
  "small_airport",
  "heliport",
  "seaplane_base",
  "balloonport",
  "closed",
] as const;

export type AirportType = (typeof AIRPORT_TYPES)[number];

export interface Airport {
  id: number;
  ident: string;
  type: AirportType;
  name: string;
  lat: number;
  lon: number;
  elevation_ft: number | null;
  continent: string | null;
  iso_country: string | null;
  iso_region: string | null;
  municipality: string | null;
  scheduled_service: string | null;
  gps_code: string | null;
  icao_code: string | null;
  iata_code: string | null;
  local_code: string | null;
  home_link: string | null;
  wikipedia_link: string | null;
  keywords: string | null;
  name_zh: string | null;
  name_zh_source: string | null;
  municipality_zh: string | null;
  municipality_zh_source: string | null;
  location_zh: string | null;
  location_zh_source: string | null;
}

export interface SnapshotMeta {
  schemaVersion: number;
  generatedAt: string;
  source: { url: string; sha256: string; rowCount: number };
  names: { file: string; sha256: string; rowCount: number };
}

export interface AirportSnapshot extends SnapshotMeta {
  airports: Airport[];
}

export interface FilterState {
  types: AirportType[];
  countries: string[];
  query: string;
  hasZh: boolean;
  scheduledOnly: boolean;
  /** 是否显示国家轮廓（只影响底图，不影响点位筛选）。 */
  borders: boolean;
}
