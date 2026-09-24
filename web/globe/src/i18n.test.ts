import { describe, expect, it } from "vitest";

import en from "./locales/en";
import zh from "./locales/zh";
import { normalizeLanguage, resolveInitialLanguage } from "./i18n";

function flatten(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flatten(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe("i18n", () => {
  it("中英词典键完全一致（避免漏翻）", () => {
    expect(flatten(en).sort()).toEqual(flatten(zh).sort());
  });

  it("语言优先级：URL > localStorage > 浏览器 > 默认 zh", () => {
    expect(resolveInitialLanguage({ search: "?lang=en", stored: "zh", navigatorLanguage: "zh-CN" })).toBe("en");
    expect(resolveInitialLanguage({ search: "", stored: "en", navigatorLanguage: "zh-CN" })).toBe("en");
    expect(resolveInitialLanguage({ search: "", stored: null, navigatorLanguage: "en-US" })).toBe("en");
    expect(resolveInitialLanguage({ search: "", stored: null, navigatorLanguage: "fr-FR" })).toBe("zh");
  });

  it("normalizeLanguage 只认中英", () => {
    expect(normalizeLanguage("zh-Hant")).toBe("zh");
    expect(normalizeLanguage("en-GB")).toBe("en");
    expect(normalizeLanguage("fr")).toBeNull();
    expect(normalizeLanguage(undefined)).toBeNull();
  });
});
