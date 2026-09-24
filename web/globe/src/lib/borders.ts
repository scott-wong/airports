import * as THREE from "three";

import { latLngToVector3 } from "./geo";

export type BorderLayer = "countries" | "provinces" | "districts";
export type BorderLevel = "coarse" | "medium" | "fine";

export interface BorderRequest {
  layer: BorderLayer;
  level: BorderLevel;
}

export interface BorderPayload {
  layer: BorderLayer;
  level: BorderLevel;
  attribution: string;
  features: { iso: string; name: string; rings: number[][] }[];
}

export const LAYER_STYLE: Record<
  BorderLayer,
  { color: string; opacity: number; altitude: number; order: number }
> = {
  countries: { color: "#5ad9ff", opacity: 0.36, altitude: 0.004, order: 0 },
  provinces: { color: "#8fe8ff", opacity: 0.24, altitude: 0.0035, order: 1 },
  districts: { color: "#c4f2ff", opacity: 0.16, altitude: 0.003, order: 2 },
};

const LEVEL_ORDER: Record<BorderLevel, number> = { coarse: 0, medium: 1, fine: 2 };

const LAYER_LEVELS: Record<BorderLayer, BorderLevel[]> = {
  countries: ["coarse", "medium", "fine"],
  provinces: ["medium", "fine"],
  districts: ["fine"],
};

export function levelForDistance(distance: number): BorderLevel {
  if (distance > 240) return "coarse";
  if (distance > 130) return "medium";
  return "fine";
}

function clampLevel(layer: BorderLayer, level: BorderLevel): BorderLevel {
  const allowed = LAYER_LEVELS[layer];
  return allowed.includes(level) ? level : allowed[allowed.length - 1];
}

/**
 * 相机距离 → 该加载哪些图层/层级：
 * 远景只有国界；拉到区域级出现省/州；贴到城市级再叠一层县/市（Natural Earth 只提供美国县）。
 */
export function borderRequests(distance: number): BorderRequest[] {
  const base = levelForDistance(distance);
  const requests: BorderRequest[] = [
    { layer: "countries", level: clampLevel("countries", base) },
  ];
  if (distance <= 240) requests.push({ layer: "provinces", level: clampLevel("provinces", base) });
  if (distance <= 112) requests.push({ layer: "districts", level: "fine" });
  return requests;
}

export function isFinerThan(candidate: BorderLevel, current: BorderLevel | null): boolean {
  if (!current) return true;
  return LEVEL_ORDER[candidate] > LEVEL_ORDER[current];
}

export function borderUrl(layer: BorderLayer, level: BorderLevel, base = import.meta.env.BASE_URL) {
  const root = base.endsWith("/") ? base : `${base}/`;
  return `${root}borders/borders-${layer}-${level}.json.gz`;
}

async function readMaybeGzip(response: Response): Promise<string> {
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const isGzip = bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
  if (!isGzip) return new TextDecoder().decode(bytes);
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}

export async function fetchBorderPayload(
  layer: BorderLayer,
  level: BorderLevel,
  base?: string,
): Promise<BorderPayload> {
  const response = await fetch(borderUrl(layer, level, base));
  if (!response.ok) {
    throw new Error(`边界数据加载失败（${layer}/${level}）：HTTP ${response.status}`);
  }
  const payload = JSON.parse(await readMaybeGzip(response)) as BorderPayload;
  if (!payload || !Array.isArray(payload.features)) {
    throw new Error(`边界数据格式异常（${layer}/${level}）`);
  }
  return payload;
}

/** 把多边形环展开成线段顶点（LineSegments 需要成对的点）。 */
export function buildBorderGeometry(payload: BorderPayload): THREE.BufferGeometry {
  const altitude = (LAYER_STYLE[payload.layer] ?? LAYER_STYLE.countries).altitude;
  let segments = 0;
  for (const feature of payload.features) {
    for (const ring of feature.rings) {
      const points = ring.length / 2;
      if (points >= 2) segments += points - 1;
    }
  }
  const positions = new Float32Array(segments * 2 * 3);
  let offset = 0;
  for (const feature of payload.features) {
    for (const ring of feature.rings) {
      for (let index = 0; index < ring.length - 2; index += 2) {
        const first = latLngToVector3(ring[index + 1], ring[index], altitude);
        const second = latLngToVector3(ring[index + 3], ring[index + 2], altitude);
        positions[offset] = first.x;
        positions[offset + 1] = first.y;
        positions[offset + 2] = first.z;
        positions[offset + 3] = second.x;
        positions[offset + 4] = second.y;
        positions[offset + 5] = second.z;
        offset += 6;
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.computeBoundingSphere();
  return geometry;
}

export function createBorderLines(payload: BorderPayload): THREE.LineSegments {
  const style = LAYER_STYLE[payload.layer] ?? LAYER_STYLE.countries;
  const material = new THREE.LineBasicMaterial({
    color: new THREE.Color(style.color),
    transparent: true,
    opacity: style.opacity,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const lines = new THREE.LineSegments(buildBorderGeometry(payload), material);
  lines.frustumCulled = false;
  lines.renderOrder = style.order;
  return lines;
}
