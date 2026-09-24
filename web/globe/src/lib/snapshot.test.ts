import { describe, expect, it } from "vitest";

import { parseSnapshot } from "./snapshot";

const fields = [
  "id",
  "ident",
  "type",
  "name",
  "latitude_deg",
  "longitude_deg",
  "municipality",
  "iso_country",
  "name_zh",
  "name_zh_source",
  "location_zh",
];

function snapshotWith(rows: unknown[][]) {
  return { schemaVersion: 1, generatedAt: "2026-09-24T00:00:00Z", fields, rows };
}

describe("parseSnapshot", () => {
  it("按 fields 表解析行，缺失字段回退为 null", () => {
    const parsed = parseSnapshot(
      snapshotWith([[1, "ZBAA", "large_airport", "Beijing Capital", 40.08, 116.58, "Beijing", "CN", "北京首都国际机场", "wikidata:Q32190:zh-cn", "北京市"]]),
    );
    expect(parsed.airports).toHaveLength(1);
    const [airport] = parsed.airports;
    expect(airport.name_zh).toBe("北京首都国际机场");
    expect(airport.location_zh).toBe("北京市");
    expect(airport.elevation_ft).toBeNull();
  });

  it("跳过坐标缺失或类型未知的行", () => {
    const parsed = parseSnapshot(
      snapshotWith([
        [1, "AAA", "large_airport", "Ok", 10, 20, null, "CN", null, null, null],
        [2, "BBB", "spaceship", "Bad type", 10, 20, null, "CN", null, null, null],
        [3, "CCC", "large_airport", "No coords", null, 20, null, "CN", null, null, null],
      ]),
    );
    expect(parsed.airports.map((airport) => airport.ident)).toEqual(["AAA"]);
  });

  it("拒绝不支持的 schemaVersion", () => {
    expect(() => parseSnapshot({ ...snapshotWith([]), schemaVersion: 99 })).toThrow(/schemaVersion/);
  });
});
