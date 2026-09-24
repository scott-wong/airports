/** globe.gl / three-globe 的地球半径（单位：three.js 单位）。 */
export const GLOBE_RADIUS = 100;

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/**
 * 经纬度 → 地球坐标系。公式与 three-globe 内部实现保持一致，
 * 否则点位会整体偏移（见 web/globe/docs/adr/0002）。
 */
export function latLngToVector3(lat: number, lon: number, altitude = 0): Vec3 {
  const phi = ((90 - lat) * Math.PI) / 180;
  const theta = ((90 - lon) * Math.PI) / 180;
  const radius = GLOBE_RADIUS * (1 + altitude);
  const phiSin = Math.sin(phi);
  return {
    x: radius * phiSin * Math.cos(theta),
    y: radius * Math.cos(phi),
    z: radius * phiSin * Math.sin(theta),
  };
}

/** 球面距离（公里），用于调试与测试。 */
export function haversineKm(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const radius = 6371.0088;
  const toRad = (value: number) => (value * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(h)));
}
