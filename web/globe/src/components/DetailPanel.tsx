import { useState } from "react";
import { useTranslation } from "react-i18next";

import { TYPE_STYLE } from "../lib/colors";
import {
  cityName,
  countryName,
  formatCoordinates,
  formatElevation,
  nameSourceKind,
  primaryName,
  secondaryName,
} from "../lib/format";
import type { Airport } from "../types";

interface Props {
  airport: Airport | null;
  language: string;
  pinned: boolean;
  onClose: () => void;
  onFocus: (airport: Airport) => void;
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 border-b border-white/5 py-1">
      <span className="w-24 shrink-0 font-mono text-[11px] uppercase tracking-wider text-hud-dim">
        {label}
      </span>
      <span className="flex-1 break-words text-[13px] text-slate-100">{value}</span>
    </div>
  );
}

export function DetailPanel({ airport, language, pinned, onClose, onFocus }: Props) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  if (!airport) {
    return (
      <aside className="hud-panel absolute right-4 top-32 z-20 hidden w-[300px] rounded-lg p-4 text-[12px] text-hud-dim lg:block">
        {t("detail.empty")}
      </aside>
    );
  }

  const style = TYPE_STYLE[airport.type];
  const kind = nameSourceKind(airport.name_zh_source);
  const badgeLabel = t(`badges.${kind}`);
  const badgeHint = t(`badges.${kind}Hint`);
  const secondary = secondaryName(airport, language);
  const city = cityName(airport, language);

  const codes = [
    airport.iata_code ? `${t("detail.iata")} ${airport.iata_code}` : null,
    airport.icao_code ? `${t("detail.icao")} ${airport.icao_code}` : null,
    airport.gps_code ? `${t("detail.gps")} ${airport.gps_code}` : null,
    airport.local_code ? `${t("detail.local")} ${airport.local_code}` : null,
  ].filter(Boolean);

  return (
    <aside className="hud-panel hud-scroll absolute right-4 top-32 z-20 max-h-[calc(100vh-9rem)] w-[320px] max-w-[86vw] overflow-y-auto rounded-lg p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold leading-snug text-hud-cyan">
            {primaryName(airport, language)}
          </h2>
          {secondary ? <p className="mt-0.5 text-[11px] text-hud-dim">{secondary}</p> : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="font-mono text-[11px] text-hud-dim hover:text-slate-100"
          aria-label={t("detail.close")}
        >
          ✕
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span
          className="badge"
          style={{ color: style.color, borderColor: style.color, background: `${style.color}18` }}
        >
          {t(style.labelKey)}
        </span>
        {airport.name_zh ? (
          <span
            className={`badge ${
              kind === "authoritative"
                ? "text-emerald-300"
                : kind === "composite"
                  ? "text-amber-300"
                  : "text-fuchsia-300"
            }`}
            title={badgeHint}
          >
            {badgeLabel}
          </span>
        ) : (
          <span className="badge text-slate-400">{t("detail.noZh")}</span>
        )}
        {pinned ? null : (
          <button
            type="button"
            onClick={() => onFocus(airport)}
            className="badge border-hud-cyan/40 text-hud-cyan hover:bg-hud-cyan/10"
          >
            focus
          </button>
        )}
      </div>

      <div className="mt-3">
        <Row label={t("detail.city")} value={city ?? undefined} />
        <Row
          label={t("detail.country")}
          value={countryName(language, airport.iso_country, airport.iso_country ?? undefined)}
        />
        <Row label={t("detail.region")} value={airport.iso_region} />
        <Row label={t("detail.continent")} value={airport.continent} />
        <Row label={t("detail.elevation")} value={formatElevation(language, airport.elevation_ft)} />
        <Row label={t("detail.codes")} value={codes.join(" · ") || undefined} />
        <Row
          label={t("detail.ident")}
          value={airport.ident === airport.name ? undefined : airport.ident}
        />
        <Row
          label={t("detail.scheduled")}
          value={
            airport.scheduled_service === "yes"
              ? t("common.yes")
              : airport.scheduled_service === "no"
                ? t("common.no")
                : undefined
          }
        />
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-hud-dim">
          {formatCoordinates(airport.lat, airport.lon)}
        </span>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard
              ?.writeText(formatCoordinates(airport.lat, airport.lon))
              .then(() => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              })
              .catch(() => undefined);
          }}
          className="font-mono text-[11px] text-hud-cyan hover:underline"
        >
          {copied ? t("detail.copied") : t("detail.copy")}
        </button>
      </div>

      {airport.home_link || airport.wikipedia_link ? (
        <div className="mt-3 flex flex-wrap gap-3 font-mono text-[11px]">
          {airport.home_link ? (
            <a
              className="text-hud-cyan hover:underline"
              href={airport.home_link}
              target="_blank"
              rel="noreferrer"
            >
              {t("detail.homepage")} ↗
            </a>
          ) : null}
          {airport.wikipedia_link ? (
            <a
              className="text-hud-cyan hover:underline"
              href={airport.wikipedia_link}
              target="_blank"
              rel="noreferrer"
            >
              {t("detail.wikipedia")} ↗
            </a>
          ) : null}
        </div>
      ) : null}

      <p className="mt-3 font-mono text-[10px] leading-relaxed text-hud-dim">
        id {airport.id} · {airport.lat.toFixed(4)}, {airport.lon.toFixed(4)}
      </p>
    </aside>
  );
}
