import { describe, expect, it } from "vitest";

import { GLOBE_RADIUS, haversineKm, latLngToVector3 } from "./geo";

describe("latLngToVector3", () => {
  it("matches three-globe 的坐标约定（否则点位会整体偏移）", () => {
    const equator = latLngToVector3(0, 0);
    expect(equator.x).toBeCloseTo(0, 6);
    expect(equator.y).toBeCloseTo(0, 6);
    expect(equator.z).toBeCloseTo(GLOBE_RADIUS, 6);
    const northPole = latLngToVector3(90, 0);
    expect(northPole.y).toBeCloseTo(GLOBE_RADIUS, 6);
    const lon90 = latLngToVector3(0, 90);
    expect(lon90.x).toBeCloseTo(GLOBE_RADIUS, 6);
  });

  it("keeps every point on the sphere and supports altitude offsets", () => {
    for (const [lat, lon] of [
      [39.9042, 116.4074],
      [-33.9461, 151.1772],
      [51.4706, -0.461941],
    ]) {
      const point = latLngToVector3(lat, lon);
      expect(Math.hypot(point.x, point.y, point.z)).toBeCloseTo(GLOBE_RADIUS, 4);
    }
    const lifted = latLngToVector3(10, 20, 0.1);
    expect(Math.hypot(lifted.x, lifted.y, lifted.z)).toBeCloseTo(GLOBE_RADIUS * 1.1, 4);
  });
});

describe("haversineKm", () => {
  it("measures Beijing → Shanghai 约 1067 km", () => {
    const distance = haversineKm({ lat: 39.9042, lon: 116.4074 }, { lat: 31.2304, lon: 121.4737 });
    expect(distance).toBeGreaterThan(1030);
    expect(distance).toBeLessThan(1100);
  });
});
