import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en";
import zh from "./locales/zh";

export const SUPPORTED_LANGUAGES = ["zh", "en"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

const STORAGE_KEY = "airport-globe.lang";

export function normalizeLanguage(value: string | null | undefined): Language | null {
  if (!value) return null;
  const lower = value.toLowerCase();
  if (lower.startsWith("zh")) return "zh";
  if (lower.startsWith("en")) return "en";
  return null;
}

export function resolveInitialLanguage(options?: {
  search?: string;
  navigatorLanguage?: string;
  stored?: string | null;
}): Language {
  const search = options?.search ?? (typeof window === "undefined" ? "" : window.location.search);
  const fromUrl = normalizeLanguage(new URLSearchParams(search).get("lang"));
  if (fromUrl) return fromUrl;
  const stored = options?.stored ?? (typeof window === "undefined" ? null : window.localStorage.getItem(STORAGE_KEY));
  const fromStorage = normalizeLanguage(stored);
  if (fromStorage) return fromStorage;
  const fromNavigator = normalizeLanguage(
    options?.navigatorLanguage ?? (typeof navigator === "undefined" ? null : navigator.language),
  );
  return fromNavigator ?? "zh";
}

export function rememberLanguage(language: Language): void {
  if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, language);
}

void i18n.use(initReactI18next).init({
  resources: {
    zh: { translation: zh },
    en: { translation: en },
  },
  lng: resolveInitialLanguage(),
  fallbackLng: "zh",
  interpolation: { escapeValue: false },
});

export default i18n;
