import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { TYPE_STYLE } from "../lib/colors";
import { formatNumber } from "../lib/format";
import type { AirportType, FilterState } from "../types";

interface Props {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
  typeCounts: Record<AirportType, number>;
  countryCounts: Map<string, number>;
  language: string;
  visibleCount: number;
}

export function FilterPanel({
  filters,
  onChange,
  typeCounts,
  countryCounts,
  language,
  visibleCount,
}: Props) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const [countryQuery, setCountryQuery] = useState("");

  const countryList = useMemo(() => {
    const entries = [...countryCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const query = countryQuery.trim().toLowerCase();
    if (!query) return entries.slice(0, 80);
    return entries.filter(([code]) => code.toLowerCase().includes(query)).slice(0, 80);
  }, [countryCounts, countryQuery]);

  const toggleType = (type: AirportType) => {
    const next = filters.types.includes(type)
      ? filters.types.filter((value) => value !== type)
      : [...filters.types, type];
    onChange({ ...filters, types: next });
  };

  const toggleCountry = (code: string) => {
    const next = filters.countries.includes(code)
      ? filters.countries.filter((value) => value !== code)
      : [...filters.countries, code];
    onChange({ ...filters, countries: next });
  };

  if (collapsed) {
    return (
      <div className="absolute bottom-4 left-4 z-20">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="hud-panel rounded-lg px-3 py-2 font-mono text-[11px] uppercase tracking-widest text-hud-cyan"
        >
          {t("filters.expand")}
        </button>
      </div>
    );
  }

  return (
    <aside className="hud-panel hud-scroll absolute bottom-4 left-4 top-32 z-20 w-[300px] max-w-[86vw] overflow-y-auto rounded-lg p-3 text-sm">
      <div className="flex items-center justify-between">
        <h2 className="hud-title text-xs text-hud-cyan">{t("filters.title")}</h2>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="font-mono text-[11px] text-hud-dim hover:text-slate-100"
        >
          {t("filters.collapse")}
        </button>
      </div>

      <section className="mt-3">
        <h3 className="font-mono text-[11px] uppercase tracking-widest text-hud-dim">
          {t("filters.type")}
        </h3>
        <ul className="mt-2 space-y-1">
          {Object.entries(TYPE_STYLE).map(([type, style]) => {
            const key = type as AirportType;
            const active = filters.types.includes(key);
            return (
              <li key={type}>
                <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-white/5">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => toggleType(key)}
                    className="h-3.5 w-3.5 accent-cyan-400"
                  />
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-full"
                    style={{ background: style.color, boxShadow: `0 0 8px ${style.color}` }}
                  />
                  <span className="flex-1 text-[13px] text-slate-200">{t(style.labelKey)}</span>
                  <span className="font-mono text-[11px] text-hud-dim">
                    {formatNumber(language, typeCounts[key] ?? 0)}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="mt-4">
        <h3 className="font-mono text-[11px] uppercase tracking-widest text-hud-dim">
          {t("filters.search")}
        </h3>
        <input
          value={filters.query}
          onChange={(event) => onChange({ ...filters, query: event.target.value })}
          placeholder={t("filters.searchPlaceholder")}
          className="mt-2 w-full rounded border border-hud-line bg-black/40 px-2 py-1 text-[13px] outline-none focus:border-hud-cyan"
        />
      </section>

      <section className="mt-4">
        <div className="flex items-center justify-between">
          <h3 className="font-mono text-[11px] uppercase tracking-widest text-hud-dim">
            {t("filters.country")}
          </h3>
          <span className="font-mono text-[10px] text-hud-dim">
            {filters.countries.length} {t("filters.selected")}
          </span>
        </div>
        <input
          value={countryQuery}
          onChange={(event) => setCountryQuery(event.target.value)}
          placeholder={t("filters.countrySearch")}
          className="mt-2 w-full rounded border border-hud-line bg-black/40 px-2 py-1 font-mono text-[12px] outline-none focus:border-hud-cyan"
        />
        <div className="mt-2 flex flex-wrap gap-1">
          {filters.countries.map((code) => (
            <button
              key={code}
              type="button"
              onClick={() => toggleCountry(code)}
              className="badge bg-hud-cyan/10 text-hud-cyan"
            >
              {code} ×
            </button>
          ))}
        </div>
        <ul className="mt-2 max-h-44 space-y-0.5 overflow-y-auto pr-1">
          {countryList.map(([code, count]) => (
            <li key={code}>
              <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-white/5">
                <input
                  type="checkbox"
                  checked={filters.countries.includes(code)}
                  onChange={() => toggleCountry(code)}
                  className="h-3.5 w-3.5 accent-cyan-400"
                />
                <span className="flex-1 font-mono text-[12px] text-slate-200">{code}</span>
                <span className="font-mono text-[10px] text-hud-dim">
                  {formatNumber(language, count)}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-4 space-y-2">
        <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-200">
          <input
            type="checkbox"
            checked={filters.hasZh}
            onChange={(event) => onChange({ ...filters, hasZh: event.target.checked })}
            className="h-3.5 w-3.5 accent-cyan-400"
          />
          {t("filters.hasZh")}
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-200">
          <input
            type="checkbox"
            checked={filters.scheduledOnly}
            onChange={(event) => onChange({ ...filters, scheduledOnly: event.target.checked })}
            className="h-3.5 w-3.5 accent-cyan-400"
          />
          {t("filters.scheduled")}
        </label>
      </section>

      <button
        type="button"
        onClick={() =>
          onChange({ types: [], countries: [], query: "", hasZh: false, scheduledOnly: false })
        }
        className="mt-4 w-full rounded border border-hud-line px-2 py-1 font-mono text-[11px] uppercase tracking-widest text-hud-dim hover:border-hud-cyan hover:text-hud-cyan"
      >
        {t("filters.reset")}
      </button>

      <p className="mt-3 font-mono text-[10px] leading-relaxed text-hud-dim">{t("hud.hint")}</p>
      <p className="mt-1 font-mono text-[10px] text-hud-dim">
        {t("hud.visible")} {formatNumber(language, visibleCount)}
      </p>
    </aside>
  );
}
