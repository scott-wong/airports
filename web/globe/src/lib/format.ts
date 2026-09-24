import type { Airport } from "../types";

const displayNamesCache = new Map<string, Intl.DisplayNames | null>();

export function countryName(locale: string, code: string | null | undefined, fallback = "—"): string {
  if (!code) return fallback;
  let display = displayNamesCache.get(locale);
  if (display === undefined) {
    try {
      display = new Intl.DisplayNames([locale], { type: "region" });
    } catch {
      display = null;
    }
    displayNamesCache.set(locale, display);
  }
  if (!display) return code;
  try {
    return display.of(code) ?? code;
  } catch {
    return code;
  }
}

export function formatNumber(locale: string, value: number): string {
  return new Intl.NumberFormat(locale).format(value);
}

export function formatCoordinates(lat: number, lon: number): string {
  const latLabel = `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? "N" : "S"}`;
  const lonLabel = `${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? "E" : "W"}`;
  return `${latLabel}, ${lonLabel}`;
}

export function formatElevation(locale: string, feet: number | null): string {
  if (feet === null) return "—";
  const meters = Math.round(feet * 0.3048);
  return `${formatNumber(locale, feet)} ft / ${formatNumber(locale, meters)} m`;
}

export function primaryName(airport: Airport, language: string): string {
  if (language.startsWith("zh")) return airport.name_zh ?? airport.name;
  return airport.name;
}

export function secondaryName(airport: Airport, language: string): string | null {
  if (language.startsWith("zh")) return airport.name_zh ? airport.name : null;
  return airport.name_zh;
}

export function cityName(airport: Airport, language: string): string | null {
  if (language.startsWith("zh")) {
    return airport.municipality_zh ?? airport.location_zh ?? airport.municipality;
  }
  return airport.municipality ?? airport.location_zh ?? null;
}

export type NameSourceKind = "authoritative" | "composite" | "llm" | "unknown";

export function nameSourceKind(source: string | null): NameSourceKind {
  if (!source) return "unknown";
  if (source.startsWith("wikidata:") || source.startsWith("wikipedia:")) return "authoritative";
  if (source.startsWith("composite:")) return "composite";
  if (source.startsWith("llm:")) return "llm";
  return "unknown";
}
