import { describe, expect, it } from "vitest";

import type { Airport } from "../types";
import { buildPickGrid, candidatesNear, cellKey, pickNearest } from "./picking";

function airport(id: number, lat: number, lon: number): Airport {
  return {
    id,
    ident: `A${id}`,
    type: "large_airport",
    name: `Airport ${id}`,
    lat,
    lon,
    elevation_ft: null,
    continent: null,
    iso_country: "CN",
    iso_region: null,
    municipality: null,
    scheduled_service: "yes",
    gps_code: null,
    icao_code: null,
    iata_code: null,
    local_code: null,
    home_link: null,
    wikipedia_link: null,
    keywords: null,
    name_zh: null,
    name_zh_source: null,
    municipality_zh: null,
    municipality_zh_source: null,
    location_zh: null,
    location_zh_source: null,
  };
}

describe("picking", () => {
  const airports = [airport(1, 10, 20), airport(2, 10.4, 20.4), airport(3, -30, 150)];

  it("网格键按 0.5° 分桶", () => {
    expect(cellKey(10, 20, 0.5)).toBe("20:40");
    expect(cellKey(10.6, 20.4, 0.5)).toBe("21:40");
  });

  it("邻域检索取回邻近点，远处点不在邻域", () => {
    const grid = buildPickGrid(airports);
    expect(candidatesNear(grid, 10.2, 20.2, 1).sort()).toEqual([0, 1]);
    expect(candidatesNear(grid, 10.2, 20.2, 1)).not.toContain(2);
    expect(candidatesNear(grid, -30, 150, 1)).toContain(2);
  });

  it("屏幕空间最近邻只在阈值内返回", () => {
    const grid = buildPickGrid(airports);
    const project = (item: Airport) => ({ x: item.lon, y: item.lat });
    const candidates = candidatesNear(grid, 10.2, 20.2, 1);
    expect(pickNearest(candidates, airports, project, { x: 20.1, y: 10.1 }, 1)?.id).toBe(1);
    expect(pickNearest(candidates, airports, project, { x: 40, y: 40 }, 1)).toBeNull();
    expect(pickNearest(candidates, airports, () => null, { x: 20, y: 10 }, 1)).toBeNull();
  });
});
