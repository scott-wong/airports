import { describe, expect, it } from "vitest";

import type { Airport } from "../types";
import { cityName, formatCoordinates, formatElevation, nameSourceKind, primaryName, secondaryName } from "./format";

const base: Airport = {
  id: 1,
  ident: "ZBAA",
  type: "large_airport",
  name: "Beijing Capital International Airport",
  lat: 40.0801,
  lon: 116.5846,
  elevation_ft: 116,
  continent: "AS",
  iso_country: "CN",
  iso_region: "CN-11",
  municipality: "Beijing",
  scheduled_service: "yes",
  gps_code: "ZBAA",
  icao_code: "ZBAA",
  iata_code: "PEK",
  local_code: null,
  home_link: null,
  wikipedia_link: null,
  keywords: null,
  name_zh: "北京首都国际机场",
  name_zh_source: "wikidata:Q32190:zh-cn",
  municipality_zh: "北京市",
  municipality_zh_source: null,
  location_zh: null,
  location_zh_source: null,
};

describe("format helpers", () => {
  it("nameSourceKind 区分权威/合成/模型", () => {
    expect(nameSourceKind("wikidata:Q1:zh-cn")).toBe("authoritative");
    expect(nameSourceKind("wikipedia:en:London>zh")).toBe("authoritative");
    expect(nameSourceKind("composite:municipality:Lae")).toBe("composite");
    expect(nameSourceKind("llm:codex:deepseek-v4.1-flash")).toBe("llm");
    expect(nameSourceKind(null)).toBe("unknown");
  });

  it("双语主副名与城市名", () => {
    expect(primaryName(base, "zh")).toBe("北京首都国际机场");
    expect(primaryName(base, "en")).toBe("Beijing Capital International Airport");
    expect(secondaryName(base, "zh")).toBe("Beijing Capital International Airport");
    expect(cityName(base, "zh")).toBe("北京市");
    expect(cityName(base, "en")).toBe("Beijing");
  });

  it("无中文名时回退英文并标注", () => {
    const noChinese: Airport = { ...base, name_zh: null, name_zh_source: null, municipality_zh: null };
    expect(primaryName(noChinese, "zh")).toBe("Beijing Capital International Airport");
    expect(secondaryName(noChinese, "zh")).toBeNull();
    expect(cityName(noChinese, "zh")).toBe("Beijing");
  });

  it("坐标与海拔格式化", () => {
    expect(formatCoordinates(40.0801, 116.5846)).toBe("40.0801° N, 116.5846° E");
    expect(formatElevation("en", 116)).toContain("116");
    expect(formatElevation("en", null)).toBe("—");
  });
});
