import { describe, expect, it } from "vitest";

import type { Airport, FilterState } from "../types";
import { DEFAULT_FILTERS, applyFilters, countByType, decodeFilters, encodeFilters, matchesFilters } from "./filters";

function airport(overrides: Partial<Airport> = {}): Airport {
  return {
    id: 1,
    ident: "ZBAA",
    type: "large_airport",
    name: "Beijing Capital International Airport",
    lat: 40.08,
    lon: 116.58,
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
    keywords: "北京 首都",
    name_zh: "北京首都国际机场",
    name_zh_source: "wikidata:Q32190:zh-cn",
    municipality_zh: "北京市",
    municipality_zh_source: "wikipedia:en:Beijing>zh",
    location_zh: "北京市",
    location_zh_source: "wikidata:Q32190:P131:Q956:zh-cn",
    ...overrides,
  };
}

describe("filters", () => {
  it("默认隐藏 small/heliport/closed", () => {
    const list = [
      airport(),
      airport({ id: 2, ident: "X1", type: "small_airport", name: "Small" }),
      airport({ id: 3, ident: "X2", type: "heliport", name: "Pad" }),
      airport({ id: 4, ident: "X3", type: "closed", name: "Gone" }),
    ];
    expect(applyFilters(list, DEFAULT_FILTERS).map((item) => item.ident)).toEqual(["ZBAA"]);
  });

  it("按类型、国家、是否有中文名、定期航班组合过滤", () => {
    const list = [
      airport(),
      airport({ id: 2, ident: "KJFK", iso_country: "US", name_zh: null, name_zh_source: null }),
      airport({ id: 3, ident: "ZZZ", scheduled_service: "no" }),
    ];
    const filters: FilterState = { ...DEFAULT_FILTERS, countries: ["US"] };
    expect(applyFilters(list, filters).map((item) => item.ident)).toEqual(["KJFK"]);
    expect(applyFilters(list, { ...filters, countries: [], hasZh: true }).map((i) => i.ident)).toEqual(["ZBAA", "ZZZ"]);
    expect(applyFilters(list, { ...filters, countries: [], scheduledOnly: true }).map((i) => i.ident)).toEqual(["ZBAA", "KJFK"]);
  });

  it("关键字命中中文名、IATA 与关键词", () => {
    const item = airport();
    expect(matchesFilters(item, { ...DEFAULT_FILTERS, query: "首都" })).toBe(true);
    expect(matchesFilters(item, { ...DEFAULT_FILTERS, query: "pek" })).toBe(true);
    expect(matchesFilters(item, { ...DEFAULT_FILTERS, query: "kennedy" })).toBe(false);
  });

  it("类型计数覆盖全部七类", () => {
    const counts = countByType([airport(), airport({ id: 2, type: "closed", ident: "X" })]);
    expect(counts.large_airport).toBe(1);
    expect(counts.closed).toBe(1);
    expect(Object.keys(counts)).toHaveLength(7);
  });

  it("URL 编码往返", () => {
    const filters: FilterState = {
      types: ["large_airport", "closed"],
      countries: ["CN", "US"],
      query: "首都 airport",
      hasZh: true,
      scheduledOnly: true,
      borders: false,
      basemap: "street",
    };
    expect(decodeFilters(encodeFilters(filters))).toEqual(filters);
    expect(decodeFilters("")).toEqual(DEFAULT_FILTERS);
    expect(decodeFilters("borders=0").borders).toBe(false);
    expect(decodeFilters("map=street").basemap).toBe("street");
    expect(decodeFilters("map=nonsense").basemap).toBe("satellite");
    expect(DEFAULT_FILTERS.basemap).toBe("satellite");
  });
});
