import { describe, expect, it } from "vitest";

import {
  LAYER_STYLE,
  borderRequests,
  buildBorderGeometry,
  isFinerThan,
  levelForDistance,
} from "./borders";
import { latLngToVector3 } from "./geo";

function payload(rings: number[][]) {
  return {
    layer: "countries" as const,
    level: "coarse" as const,
    attribution: "Natural Earth (public domain)",
    features: [{ iso: "CN", name: "China", rings }],
  };
}

describe("border detail levels", () => {
  it("按相机距离选择粗细", () => {
    expect(levelForDistance(400)).toBe("coarse");
    expect(levelForDistance(200)).toBe("medium");
    expect(levelForDistance(120)).toBe("fine");
  });

  it("远景只有国界，区域加省界，城市级再加县界", () => {
    expect(borderRequests(400)).toEqual([{ layer: "countries", level: "coarse" }]);
    expect(borderRequests(200)).toEqual([
      { layer: "countries", level: "medium" },
      { layer: "provinces", level: "medium" },
    ]);
    expect(borderRequests(105)).toEqual([
      { layer: "countries", level: "fine" },
      { layer: "provinces", level: "fine" },
      { layer: "districts", level: "fine" },
    ]);
  });

  it("只允许向更细的方向升级", () => {
    expect(isFinerThan("medium", "coarse")).toBe(true);
    expect(isFinerThan("fine", "medium")).toBe(true);
    expect(isFinerThan("medium", "fine")).toBe(false);
    expect(isFinerThan("coarse", "coarse")).toBe(false);
  });
});

describe("buildBorderGeometry", () => {
  it("把环展开成线段，并对齐 three-globe 坐标", () => {
    const geometry = buildBorderGeometry(payload([[0, 0, 10, 0, 10, 10, 0, 0]]));
    const positions = geometry.getAttribute("position").array as Float32Array;
    expect(positions.length).toBe(18);
    const first = latLngToVector3(0, 0, LAYER_STYLE.countries.altitude);
    expect(positions[0]).toBeCloseTo(first.x, 5);
    expect(positions[1]).toBeCloseTo(first.y, 5);
    expect(positions[2]).toBeCloseTo(first.z, 5);
  });

  it("忽略点数不足的环", () => {
    const geometry = buildBorderGeometry(payload([[0, 0], [0, 0, 10, 0]]));
    expect(geometry.getAttribute("position").array.length).toBe(6);
  });

  it("多个要素累加线段数量", () => {
    const geometry = buildBorderGeometry({
      layer: "countries",
      level: "fine",
      attribution: "Natural Earth (public domain)",
      features: [
        { iso: "CN", name: "China", rings: [[0, 0, 1, 0, 1, 1]] },
        { iso: "JP", name: "Japan", rings: [[10, 10, 11, 10, 11, 11]] },
      ],
    });
    expect(geometry.getAttribute("position").array.length).toBe(24);
  });
});
