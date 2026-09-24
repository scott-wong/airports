"""从 Natural Earth（公共领域）生成渐进式国家轮廓，供地球页面按缩放级别懒加载。

三级数据：
  coarse ← ne_110m（全球远景，约 0.2 MB gzip）
  medium ← ne_50m （区域级，约 0.5 MB gzip）
  fine   ← ne_10m （城市级，约 2 MB gzip，只在放大时才下载）

输出是我们自己的紧凑格式：每个国家只保留 ISO/名称与"扁平化"的环坐标
（[lon, lat, lon, lat, ...]），并按级别做 Douglas–Peucker 抽稀、去掉过小的岛，
比原 GeoJSON 小一个数量级。
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

SOURCE_BASE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
)
ATTRIBUTION = "Natural Earth (public domain)"


class BordersError(RuntimeError):
    """国界数据下载或解析失败。"""


@dataclass(frozen=True)
class LevelSpec:
    name: str
    source: str
    tolerance: float
    min_area: float
    precision: int


LEVELS: tuple[LevelSpec, ...] = (
    LevelSpec("coarse", "ne_110m_admin_0_countries.geojson", 0.02, 2.0, 2),
    LevelSpec("medium", "ne_50m_admin_0_countries.geojson", 0.01, 0.05, 3),
    LevelSpec("fine", "ne_10m_admin_0_countries.geojson", 0.003, 0.002, 4),
)

LEVEL_BY_NAME = {spec.name: spec for spec in LEVELS}

Point = tuple[float, float]


def download_borders(http_client: httpx.Client, spec: LevelSpec) -> dict[str, Any]:
    url = f"{SOURCE_BASE}/{spec.source}"
    try:
        response = http_client.get(url, timeout=180.0, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as error:
        raise BordersError(f"下载 {url} 失败: {error}") from error
    except ValueError as error:
        raise BordersError(f"{url} 不是合法 JSON") from error
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise BordersError(f"{url} 不是 FeatureCollection")
    return payload


def _ring_points(ring: Sequence[Sequence[float]]) -> list[Point]:
    return [(float(point[0]), float(point[1])) for point in ring if len(point) >= 2]


def _perpendicular_distance(point: Point, start: Point, end: Point) -> float:
    if start == end:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    x0, y0 = point
    x1, y1 = start
    x2, y2 = end
    numerator = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denominator = math.hypot(y2 - y1, x2 - x1)
    return numerator / denominator


def simplify_ring(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Douglas–Peucker 抽稀（平面近似；在此容差下与球面差异可忽略）。"""
    if len(points) <= 3 or tolerance <= 0:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack: list[tuple[int, int]] = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        max_distance = 0.0
        index = -1
        for position in range(start + 1, end):
            distance = _perpendicular_distance(points[position], points[start], points[end])
            if distance > max_distance:
                max_distance = distance
                index = position
        if index != -1 and max_distance > tolerance:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [point for point, kept in zip(points, keep) if kept]


def ring_area(points: Sequence[Point]) -> float:
    """鞋带公式，单位是平方度（只用于"这个岛值不值得画"的判断）。"""
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def _iter_polygons(geometry: dict[str, Any]) -> Iterable[list[list[Point]]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        yield [_ring_points(ring) for ring in coordinates]
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            yield [_ring_points(ring) for ring in polygon]


def build_level(
    geojson: dict[str, Any],
    spec: LevelSpec,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    ring_count = 0
    point_count = 0
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        iso = properties.get("ISO_A2") or properties.get("ADM0_A3") or properties.get("SOV_A3") or ""
        name = properties.get("NAME_ZH") or properties.get("NAME") or properties.get("ADMIN") or ""
        rings: list[list[float]] = []
        for polygon in _iter_polygons(geometry):
            for ring_index, ring in enumerate(polygon):
                if len(ring) < 4:
                    continue
                # 只对小岛做面积过滤，内环（洞）照常保留
                if ring_index == 0 and ring_area(ring) < spec.min_area:
                    continue
                simplified = simplify_ring(ring, spec.tolerance)
                if len(simplified) < 4:
                    continue
                flattened: list[float] = []
                for lon, lat in simplified:
                    flattened.append(round(lon, spec.precision))
                    flattened.append(round(lat, spec.precision))
                rings.append(flattened)
                ring_count += 1
                point_count += len(simplified)
        if rings:
            features.append({"iso": str(iso), "name": str(name), "rings": rings})
    return {
        "level": spec.name,
        "attribution": ATTRIBUTION,
        "tolerance": spec.tolerance,
        "minArea": spec.min_area,
        "precision": spec.precision,
        "features": features,
        "stats": {"features": len(features), "rings": ring_count, "points": point_count},
    }


def write_level(payload: dict[str, Any], out_dir: Path) -> tuple[Path, int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path = out_dir / f"borders-{payload['level']}.json.gz"
    path.write_bytes(gzip.compress(raw, 9))
    return path, len(raw), path.stat().st_size


def export_borders(
    out_dir: Path,
    http_client: httpx.Client,
    *,
    levels: Sequence[str] | None = None,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    specs = [LEVEL_BY_NAME[name] for name in levels] if levels else list(LEVELS)
    results: dict[str, Any] = {}
    for spec in specs:
        if on_progress:
            on_progress(f"下载 {spec.source}（{spec.name}）")
        geojson = download_borders(http_client, spec)
        payload = build_level(geojson, spec)
        path, raw_bytes, stored_bytes = write_level(payload, out_dir)
        results[spec.name] = {
            "path": path.name,
            "rawBytes": raw_bytes,
            "storedBytes": stored_bytes,
            "stats": payload["stats"],
            "source": f"{SOURCE_BASE}/{spec.source}",
            "tolerance": spec.tolerance,
            "minArea": spec.min_area,
            "precision": spec.precision,
        }
        if on_progress:
            on_progress(
                f"  {spec.name}: {payload['stats']['features']} 个国家 / "
                f"{payload['stats']['points']} 个点 → {stored_bytes / 1024:.0f} KB"
            )
    manifest = {"attribution": ATTRIBUTION, "levels": results}
    (out_dir / "borders-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
