import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { DetailPanel } from "./components/DetailPanel";
import { FilterPanel } from "./components/FilterPanel";
import { GlobeView, type GlobeHandle } from "./components/Globe";
import { HudHeader } from "./components/HudHeader";
import { normalizeLanguage, rememberLanguage, type Language } from "./i18n";
import type { BorderLevel } from "./lib/borders";
import { countByType, countryCounts, decodeFilters, encodeFilters, applyFilters, DEFAULT_FILTERS } from "./lib/filters";
import { fetchSnapshot } from "./lib/snapshot";
import type { Airport, AirportSnapshot, FilterState } from "./types";

export default function App() {
  const { t, i18n } = useTranslation();
  const [snapshot, setSnapshot] = useState<AirportSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(() =>
    typeof window === "undefined" ? DEFAULT_FILTERS : decodeFilters(window.location.search),
  );
  const [selected, setSelected] = useState<Airport | null>(null);
  const [hovered, setHovered] = useState<Airport | null>(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [detailLevel, setDetailLevel] = useState<BorderLevel>("coarse");
  const globeRef = useRef<GlobeHandle | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchSnapshot()
      .then(setSnapshot)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(encodeFilters(filters));
    if (i18n.language) params.set("lang", i18n.language);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [filters, i18n.language]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
      if (event.key === " ") {
        event.preventDefault();
        setAutoRotate((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const airports = snapshot?.airports ?? [];
  const visible = useMemo(() => applyFilters(airports, filters), [airports, filters]);
  const typeCounts = useMemo(() => countByType(airports), [airports]);
  const countries = useMemo(() => countryCounts(airports), [airports]);

  const handleHover = useCallback((airport: Airport | null) => setHovered(airport), []);
  const handleSelect = useCallback((airport: Airport | null) => setSelected(airport), []);
  const detailAirport = selected ?? hovered;

  const changeLanguage = (language: Language) => {
    void i18n.changeLanguage(language);
    rememberLanguage(language);
  };

  const currentLanguage = normalizeLanguage(i18n.language) ?? "zh";

  if (error) {
    return (
      <main className="flex h-full flex-col items-center justify-center gap-3 text-center">
        <h1 className="hud-title text-sm text-hud-cyan">{t("app.error")}</h1>
        <p className="max-w-md font-mono text-[12px] text-hud-dim">{error}</p>
        <button
          type="button"
          onClick={load}
          className="hud-panel rounded px-4 py-2 font-mono text-[12px] uppercase tracking-widest text-hud-cyan"
        >
          {t("app.retry")}
        </button>
      </main>
    );
  }

  return (
    <main className="relative h-full w-full overflow-hidden">
      <GlobeView
        ref={globeRef}
        airports={visible}
        selected={selected}
        onHover={handleHover}
        onSelect={handleSelect}
        autoRotate={autoRotate}
        borders={filters.borders}
        onDetailLevel={setDetailLevel}
      />
      <div className="vignette" />

      <HudHeader
        visibleCount={visible.length}
        totalCount={airports.length}
        generatedAt={snapshot?.generatedAt ?? ""}
        language={currentLanguage}
        onLanguageChange={changeLanguage}
        detailLevel={detailLevel}
      />

      <FilterPanel
        filters={filters}
        onChange={setFilters}
        typeCounts={typeCounts}
        countryCounts={countries}
        language={currentLanguage}
        visibleCount={visible.length}
      />

      <DetailPanel
        airport={detailAirport}
        language={currentLanguage}
        pinned={selected !== null}
        onClose={() => setSelected(null)}
        onFocus={(airport) => {
          setSelected(airport);
          globeRef.current?.focus(airport);
        }}
      />

      {!snapshot ? (
        <div className="absolute inset-x-0 bottom-6 text-center font-mono text-[12px] text-hud-dim">
          {t("app.loading")}
        </div>
      ) : null}

      <footer className="pointer-events-none absolute bottom-2 right-4 z-10 font-mono text-[10px] text-hud-dim">
        {snapshot ? `${snapshot.source.sha256.slice(0, 10)} · ${airports.length}` : null}
      </footer>
    </main>
  );
}
