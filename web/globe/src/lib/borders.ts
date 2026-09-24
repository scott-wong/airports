import * as THREE from "three";

import { latLngToVector3 } from "./geo";

export type BorderLevel = "coarse" | "medium" | "fine";

export const BORDER_LEVELS: BorderLevel[] = ["coarse", "medium", "fine"];

/** 国界线略高于球面，但低于点位，避免与球体 z-fighting。 */
export const BORDER_ALTITUDE = 0.004;

export const BORDER_COLOR = "#3fa8d8";

export interface BorderPayload {
  level: BorderLevel;
  attribution: string;
  features: { iso: string; name: string; rings: number[][] }[];
}

const LEVEL_ORDER: Record<BorderLevel, number> = { coarse: 0, medium: 1, fine: 2 };

/** 相机距离 → 需要的边界精细度：拉远用粗线，贴近才下载精细线。 */
export function levelForDistance(distance: number): BorderLevel {
  if (distance > 260) return "coarse";
  if (distance > 170) return "medium";
  return "fine";
}

export function isFinerThan(candidate: BorderLevel, current: BorderLevel | null): boolean {
  if (!current) return true;
  return LEVEL_ORDER[candidate] > LEVEL_ORDER[current];
}

export function borderUrl(level: BorderLevel, base = import.meta.env.BASE_URL): string {
  const root = base.endsWith("/") ? base : `${base}/`;
  return `${root}borders/borders-${level}.json.gz`;
}

export async function fetchBorderPayload(level: BorderLevel, base?: string): Promise<BorderPayload> {
  const response = await fetch(borderUrl(level, base));
  if (!response.ok) throw new Error(`国界数据加载失败（${level}）：HTTP ${response.status}`);
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const isGzip = bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
  const text = isGzip
    ? await new Response(
        new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip")),
      ).text()
    : new TextDecoder().decode(bytes);
  const payload = JSON.parse(text) as BorderPayload;
  if (!payload || !Array.isArray(payload.features)) {
    throw new Error(`国界数据格式异常（${level}）`);
  }
  return payload;
}

/** 把国家的多边形环展开成线段顶点（LineSegments 需要成对的点）。 */
export function buildBorderGeometry(payload: BorderPayload): THREE.BufferGeometry {
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
        const lon1 = ring[index];
        const lat1 = ring[index + 1];
        const lon2 = ring[index + 2];
        const lat2 = ring[index + 3];
        const first = latLngToVector3(lat1, lon1, BORDER_ALTITUDE);
        const second = latLngToVector3(lat2, lon2, BORDER_ALTITUDE);
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

export function makeBorderMaterial(opacity = 0.34): THREE.LineBasicMaterial {
  return new THREE.LineBasicMaterial({
    color: new THREE.Color(BORDER_COLOR),
    transparent: true,
    opacity,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
}

export function createBorderLines(
  payload: BorderPayload,
  opacity?: number,
): THREE.LineSegments {
  const lines = new THREE.LineSegments(buildBorderGeometry(payload), makeBorderMaterial(opacity));
  lines.frustumCulled = false;
  return lines;
}
