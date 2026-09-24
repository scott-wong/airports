import { useTranslation } from "react-i18next";

import { SUPPORTED_LANGUAGES, type Language } from "../i18n";
import { formatNumber } from "../lib/format";

interface Props {
  visibleCount: number;
  totalCount: number;
  generatedAt: string;
  language: string;
  onLanguageChange: (language: Language) => void;
}

export function HudHeader({
  visibleCount,
  totalCount,
  generatedAt,
  language,
  onLanguageChange,
}: Props) {
  const { t } = useTranslation();
  const stamp = generatedAt ? new Date(generatedAt) : null;
  const stampLabel =
    stamp && !Number.isNaN(stamp.getTime())
      ? stamp.toLocaleString(language === "en" ? "en-GB" : "zh-CN", {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          timeZone: "UTC",
          timeZoneName: "short",
        })
      : "—";

  return (
    <header className="pointer-events-none absolute left-4 right-4 top-4 z-20 flex flex-wrap items-start justify-between gap-3">
      <div className="hud-panel pointer-events-auto rounded-lg px-4 py-3">
        <h1 className="hud-title text-sm font-semibold text-hud-cyan">{t("app.title")}</h1>
        <p className="mt-1 text-[11px] text-hud-dim">{t("app.subtitle")}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-hud-dim">
          <span>
            <span className="text-hud-cyan">{t("hud.visible")}</span>{" "}
            <span className="text-slate-100">{formatNumber(language, visibleCount)}</span>{" "}
            {t("hud.of")} {formatNumber(language, totalCount)}
          </span>
          <span>
            <span className="text-hud-cyan">{t("hud.generated")}</span> {stampLabel}
          </span>
        </div>
      </div>

      <div className="hud-panel pointer-events-auto flex items-center gap-2 rounded-lg px-3 py-2">
        <span className="font-mono text-[11px] uppercase tracking-widest text-hud-dim">
          {t("hud.language")}
        </span>
        <div className="flex overflow-hidden rounded border border-hud-line">
          {SUPPORTED_LANGUAGES.map((code) => (
            <button
              key={code}
              type="button"
              onClick={() => onLanguageChange(code)}
              className={`px-2 py-0.5 font-mono text-[11px] uppercase transition ${
                language === code
                  ? "bg-hud-cyan/20 text-hud-cyan"
                  : "text-hud-dim hover:text-slate-100"
              }`}
            >
              {code}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
