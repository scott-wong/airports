import { describe, expect, it } from "vitest";

import { BORDER_ALTITUDE, buildBorderGeometry, isFinerThan, levelForDistance } from "./borders";
import { latLngToVector3 } from "./geo";

function payload(rings: number[][]) {
  return {
    level: "coarse" as const,
    attribution: "Natural Earth (public domain)",
    features: [{ iso: "CN", name: "China", rings }],
  };
}

describe("border detail levels", () => {
  it("按相机距离选择层级：拉远粗、贴近细", () => {
    expect(levelForDistance(400)).toBe("coarse");
    expect(levelForDistance(300)).toBe("coarse");
    expect(levelForDistance(240)).toBe("medium");
    expect(levelForDistance(171)).toBe("medium");
    expect(levelForDistance(150)).toBe("fine");
    expect(levelForDistance(112)).toBe("fine");
  });

  it("只允许向更细的方向升级", () => {
    expect(isFinerThan("coarse", null)).toBe(true);
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
    // 4 个点 → 3 段 → 18 个浮点数
    expect(positions.length).toBe(18);
    const first = latLngToVector3(0, 0, BORDER_ALTITUDE);
    expect(positions[0]).toBeCloseTo(first.x, 5);
    expect(positions[1]).toBeCloseTo(first.y, 5);
    expect(positions[2]).toBeCloseTo(first.z, 5);
  });

  it("忽略点数不足的环", () => {
    const geometry = buildBorderGeometry(payload([[0, 0], [0, 0, 10, 0]]));
    expect(geometry.getAttribute("position").array.length).toBe(6);
  });

  it("多个国家/环累加线段数量", () => {
    const geometry = buildBorderGeometry({
      level: "fine",
      attribution: "Natural Earth (public domain)",
      features: [
        { iso: "CN", name: "China", rings: [[0, 0, 1, 0, 1, 1]] },
        { iso: "JP", name: "Japan", rings: [[10, 10, 11, 10, 11, 11]] },
      ],
    });
    // 两个环各 3 个点 → 各 2 段 → 每个线段 2 个顶点 × 3 个浮点 = 24
    expect(geometry.getAttribute("position").array.length).toBe(24);
  });
});
