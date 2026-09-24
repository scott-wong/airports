import type { Airport } from "../types";

export interface PickGrid {
  cellSize: number;
  cells: Map<string, number[]>;
}

export function cellKey(lat: number, lon: number, cellSize: number): string {
  return `${Math.floor(lat / cellSize)}:${Math.floor(lon / cellSize)}`;
}

/** 预建 0.5° 经纬网格索引，避免每次 hover 都遍历 8.6 万点。 */
export function buildPickGrid(airports: Airport[], cellSize = 0.5): PickGrid {
  const cells = new Map<string, number[]>();
  airports.forEach((airport, position) => {
    const key = cellKey(airport.lat, airport.lon, cellSize);
    const bucket = cells.get(key);
    if (bucket) bucket.push(position);
    else cells.set(key, [position]);
  });
  return { cellSize, cells };
}

export function candidatesNear(grid: PickGrid, lat: number, lon: number, rings = 1): number[] {
  const { cellSize } = grid;
  const baseLat = Math.floor(lat / cellSize);
  const baseLon = Math.floor(lon / cellSize);
  const found: number[] = [];
  for (let dLat = -rings; dLat <= rings; dLat += 1) {
    for (let dLon = -rings; dLon <= rings; dLon += 1) {
      const bucket = grid.cells.get(`${baseLat + dLat}:${baseLon + dLon}`);
      if (bucket) found.push(...bucket);
    }
  }
  return found;
}

export interface ScreenPoint {
  x: number;
  y: number;
}

export function pickNearest(
  candidates: number[],
  airports: Airport[],
  project: (airport: Airport) => ScreenPoint | null,
  cursor: ScreenPoint,
  maxPx = 12,
): Airport | null {
  let best: Airport | null = null;
  let bestDistance = maxPx * maxPx;
  for (const position of candidates) {
    const airport = airports[position];
    if (!airport) continue;
    const point = project(airport);
    if (!point) continue;
    const dx = point.x - cursor.x;
    const dy = point.y - cursor.y;
    const distance = dx * dx + dy * dy;
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = airport;
    }
  }
  return best;
}
