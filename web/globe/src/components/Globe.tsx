import { useCallback, useEffect, useImperativeHandle, useRef, forwardRef } from "react";
import Globe, { type GlobeInstance } from "globe.gl";
import * as THREE from "three";

import {
  type BorderLayer,
  type BorderLevel,
  borderRequests,
  createBorderLines,
  fetchBorderPayload,
  isFinerThan,
} from "../lib/borders";
import { GLOBE_RADIUS, latLngToVector3 } from "../lib/geo";
import { POINT_ALTITUDE, buildGeometry, createStarfield, makePointsMaterial } from "../lib/points";
import { buildPickGrid, candidatesNear, pickNearest, type PickGrid } from "../lib/picking";
import type { Airport, BasemapStyle } from "../types";

export interface GlobeHandle {
  focus: (airport: Airport) => void;
}

interface GlobeProps {
  airports: Airport[];
  selected: Airport | null;
  onHover: (airport: Airport | null) => void;
  onSelect: (airport: Airport | null) => void;
  autoRotate: boolean;
  borders: boolean;
  basemap: BasemapStyle;
  onDetailLevel?: (level: BorderLevel) => void;
}

/** 拉远时只保留这些类型，避免 8.6 万点糊成一团（见 ADR-0002）。 */
const COARSE_TYPES = new Set(["large_airport", "medium_airport", "seaplane_base", "balloonport"]);
const COARSE_DISTANCE = 380;
const MIN_DISTANCE = GLOBE_RADIUS * 1.045;
const MAX_DISTANCE = GLOBE_RADIUS * 6;

interface TileEngine {
  globeTileEngineUrl: (fn: ((x: number, y: number, level: number) => string) | null) => void;
  globeTileEngineMaxLevel: (level: number) => void;
  globeTileEngineClearCache: () => void;
}

export const BASEMAP_TILES: Record<
  Exclude<BasemapStyle, "wireframe">,
  { url: (x: number, y: number, level: number) => string; maxLevel: number; attribution: string }
> = {
  satellite: {
    url: (x, y, level) =>
      `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/${level}/${y}/${x}.jpg`,
    maxLevel: 15,
    attribution: "Sentinel-2 cloudless by EOX (CC BY-NC-SA 4.0)",
  },
  street: {
    url: (x, y, level) => `https://tile.openstreetmap.org/${level}/${x}/${y}.png`,
    maxLevel: 17,
    attribution: "© OpenStreetMap contributors",
  },
};

export const GlobeView = forwardRef<GlobeHandle, GlobeProps>(function GlobeView(
  { airports, selected, onHover, onSelect, autoRotate, borders, basemap, onDetailLevel },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<GlobeInstance | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  const markerRef = useRef<THREE.Points | null>(null);
  const airportsRef = useRef<Airport[]>(airports);
  const gridRef = useRef<PickGrid | null>(null);
  const coarseRef = useRef(false);
  const idleTimerRef = useRef<number | null>(null);
  const autoRotateRef = useRef(autoRotate);
  const basemapRef = useRef(basemap);
  const borderLayersRef = useRef<
    Map<BorderLayer, { level: BorderLevel; object: THREE.LineSegments }>
  >(new Map());
  const borderRequestsRef = useRef(new Set<string>());
  const detailLevelCallbackRef = useRef(onDetailLevel);
  const bordersVisibleRef = useRef(borders);

  const rebuildPoints = useCallback((list: Airport[], coarse: boolean) => {
    const points = pointsRef.current;
    if (!points) return;
    const rendered = coarse ? list.filter((airport) => COARSE_TYPES.has(airport.type)) : list;
    const previous = points.geometry;
    points.geometry = buildGeometry(rendered);
    previous?.dispose();
    // 拾取必须针对"真正画出来的那批点"，否则抽稀后下标会错位。
    airportsRef.current = rendered;
    gridRef.current = buildPickGrid(rendered);
  }, []);

  /** 按需加载某一图层；只向更细的方向升级，并在加载完成后替换旧对象。 */
  const ensureBorder = useCallback((layer: BorderLayer, level: BorderLevel) => {
    const current = borderLayersRef.current.get(layer);
    if (!isFinerThan(level, current?.level ?? null)) return;
    const key = `${layer}:${level}`;
    if (borderRequestsRef.current.has(key)) return;
    borderRequestsRef.current.add(key);
    void fetchBorderPayload(layer, level)
      .then((payload) => {
        const globe = globeRef.current;
        if (!globe) return;
        const previous = borderLayersRef.current.get(layer);
        if (previous) {
          globe.scene().remove(previous.object);
          previous.object.geometry.dispose();
          (previous.object.material as THREE.Material).dispose();
        }
        const object = createBorderLines(payload);
        object.visible = bordersVisibleRef.current;
        globe.scene().add(object);
        borderLayersRef.current.set(layer, { level, object });
      })
      .catch((error: unknown) => {
        console.warn("边界加载失败", error);
      })
      .finally(() => {
        borderRequestsRef.current.delete(key);
      });
  }, []);

  const applyBorders = useCallback(
    (distance: number) => {
      const requests = borderRequests(distance);
      for (const { layer, level } of requests) ensureBorder(layer, level);
      const countries = requests.find((item) => item.layer === "countries");
      if (countries) detailLevelCallbackRef.current?.(countries.level);
    },
    [ensureBorder],
  );

  const applyBasemap = useCallback((style: BasemapStyle) => {
    const globe = globeRef.current;
    if (!globe) return;
    const tiled = globe as unknown as TileEngine;
    if (style === "wireframe") {
      tiled.globeTileEngineUrl(null);
      tiled.globeTileEngineClearCache();
      const material = globe.globeMaterial() as THREE.MeshPhongMaterial;
      material.color = new THREE.Color("#071a2c");
      material.emissive = new THREE.Color("#0b2a42");
      material.emissiveIntensity = 0.5;
      material.needsUpdate = true;
      return;
    }
    const config = BASEMAP_TILES[style];
    tiled.globeTileEngineMaxLevel(config.maxLevel);
    tiled.globeTileEngineUrl(config.url);
    tiled.globeTileEngineClearCache();
  }, []);

  const applyView = useCallback((airport: Airport) => {
    globeRef.current?.pointOfView({ lat: airport.lat, lng: airport.lon, altitude: 0.55 }, 900);
  }, []);

  useImperativeHandle(ref, () => ({ focus: applyView }), [applyView]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const globe = new Globe(container, { animateIn: true });
    globe
      .backgroundColor("rgba(0,0,0,0)")
      .showAtmosphere(true)
      .atmosphereColor("#2f9fd8")
      .atmosphereAltitude(0.22)
      .showGraticules(true)
      .globeMaterial(
        new THREE.MeshPhongMaterial({
          color: "#071a2c",
          emissive: "#0b2a42",
          emissiveIntensity: 0.5,
          shininess: 8,
        }),
      );
    globe.pointOfView({ lat: 28, lng: 108, altitude: 2.2 }, 1600);

    const controls = globe.controls();
    controls.autoRotate = autoRotateRef.current;
    controls.autoRotateSpeed = 0.3;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.55;
    controls.zoomSpeed = 0.7;
    controls.minDistance = MIN_DISTANCE;
    controls.maxDistance = MAX_DISTANCE;

    const points = new THREE.Points(new THREE.BufferGeometry(), makePointsMaterial());
    points.frustumCulled = false;
    globe.scene().add(points);
    pointsRef.current = points;

    const marker = new THREE.Points(new THREE.BufferGeometry(), makePointsMaterial());
    marker.frustumCulled = false;
    marker.visible = false;
    globe.scene().add(marker);
    markerRef.current = marker;

    globe.scene().add(createStarfield());
    globe.scene().add(new THREE.AmbientLight(0x6688aa, 1.1));

    globeRef.current = globe;
    (window as unknown as { __airportGlobe?: GlobeInstance }).__airportGlobe = globe;

    applyBasemap(basemapRef.current);
    applyBorders(globe.camera().position.length());

    const pauseRotation = () => {
      controls.autoRotate = false;
      if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current);
      idleTimerRef.current = window.setTimeout(() => {
        controls.autoRotate = autoRotateRef.current;
      }, 10000);
    };
    container.addEventListener("pointerdown", pauseRotation);
    container.addEventListener("wheel", pauseRotation, { passive: true });

    let coarseTimer: number | null = null;
    const onControlsChange = () => {
      if (coarseTimer) return;
      coarseTimer = window.setTimeout(() => {
        coarseTimer = null;
        const distance = globe.camera().position.length();
        const coarse = distance > COARSE_DISTANCE;
        if (coarse !== coarseRef.current) {
          coarseRef.current = coarse;
          rebuildPoints(airportsRef.current, coarse);
        }
        applyBorders(distance);
      }, 180);
    };
    controls.addEventListener("change", onControlsChange);

    let frame = 0;
    const animate = () => {
      frame = window.requestAnimationFrame(animate);
      controls.update();
      const time = performance.now() / 1000;
      (points.material as THREE.ShaderMaterial).uniforms.uTime.value = time;
      (marker.material as THREE.ShaderMaterial).uniforms.uTime.value = time;
    };
    frame = window.requestAnimationFrame(animate);

    return () => {
      window.cancelAnimationFrame(frame);
      if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current);
      container.removeEventListener("pointerdown", pauseRotation);
      container.removeEventListener("wheel", pauseRotation);
      controls.removeEventListener("change", onControlsChange);
      (globe as unknown as { _destructor?: () => void })._destructor?.();
      for (const { object } of borderLayersRef.current.values()) {
        object.geometry.dispose();
        (object.material as THREE.Material).dispose();
      }
      borderLayersRef.current.clear();
      points.geometry.dispose();
      (points.material as THREE.Material).dispose();
      marker.geometry.dispose();
      (marker.material as THREE.Material).dispose();
      globeRef.current = null;
      pointsRef.current = null;
      markerRef.current = null;
    };
  }, [applyBasemap, applyBorders, rebuildPoints]);

  useEffect(() => {
    airportsRef.current = airports;
    rebuildPoints(airports, coarseRef.current);
    onHover(null);
  }, [airports, rebuildPoints, onHover]);

  useEffect(() => {
    const globe = globeRef.current;
    const marker = markerRef.current;
    if (!globe || !marker) return;
    if (!selected) {
      marker.visible = false;
      return;
    }
    marker.visible = true;
    marker.geometry.dispose();
    marker.geometry = buildGeometry([selected]);
    const material = marker.material as THREE.ShaderMaterial;
    material.uniforms.uPixelRatio.value = Math.min(window.devicePixelRatio || 1, 2) * 2.4;
  }, [selected]);

  useEffect(() => {
    detailLevelCallbackRef.current = onDetailLevel;
  }, [onDetailLevel]);

  useEffect(() => {
    bordersVisibleRef.current = borders;
    for (const { object } of borderLayersRef.current.values()) object.visible = borders;
  }, [borders]);

  useEffect(() => {
    basemapRef.current = basemap;
    applyBasemap(basemap);
  }, [basemap, applyBasemap]);

  useEffect(() => {
    autoRotateRef.current = autoRotate;
    const controls = globeRef.current?.controls();
    if (controls && autoRotate) controls.autoRotate = true;
  }, [autoRotate]);

  useEffect(() => {
    const container = containerRef.current;
    const globe = globeRef.current;
    if (!container || !globe) return;
    let raf = 0;
    let pending: { x: number; y: number } | null = null;

    const project = (airport: Airport, cameraPosition: THREE.Vector3) => {
      const world = latLngToVector3(airport.lat, airport.lon, POINT_ALTITUDE);
      const facing =
        world.x * cameraPosition.x + world.y * cameraPosition.y + world.z * cameraPosition.z;
      if (facing < GLOBE_RADIUS * GLOBE_RADIUS * 0.92) return null;
      const screen = globe.getScreenCoords(airport.lat, airport.lon, POINT_ALTITUDE);
      return { x: screen.x, y: screen.y };
    };

    const resolvePick = () => {
      raf = 0;
      if (!pending) return;
      const cursor = pending;
      pending = null;
      const geo = globe.toGlobeCoords(cursor.x, cursor.y);
      const list = airportsRef.current;
      const grid = gridRef.current;
      if (!geo || !grid || list.length === 0) {
        onHover(null);
        return;
      }
      const cameraPosition = globe.camera().position;
      for (const rings of [1, 2, 4]) {
        const candidates = candidatesNear(grid, geo.lat, geo.lng, rings);
        const hit = pickNearest(
          candidates,
          list,
          (airport) => project(airport, cameraPosition),
          cursor,
          12,
        );
        if (hit) {
          onHover(hit);
          return;
        }
      }
      onHover(null);
    };

    const onPointerMove = (event: PointerEvent) => {
      const rect = container.getBoundingClientRect();
      pending = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      if (!raf) raf = window.requestAnimationFrame(resolvePick);
    };

    const onClick = (event: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const cursor = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const geo = globe.toGlobeCoords(cursor.x, cursor.y);
      const list = airportsRef.current;
      const grid = gridRef.current;
      if (!geo || !grid) {
        onSelect(null);
        return;
      }
      const cameraPosition = globe.camera().position;
      for (const rings of [1, 2, 4]) {
        const candidates = candidatesNear(grid, geo.lat, geo.lng, rings);
        const hit = pickNearest(
          candidates,
          list,
          (airport) => project(airport, cameraPosition),
          cursor,
          14,
        );
        if (hit) {
          onSelect(hit);
          onHover(hit);
          return;
        }
      }
      onSelect(null);
    };

    container.addEventListener("pointermove", onPointerMove);
    container.addEventListener("click", onClick);
    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      container.removeEventListener("pointermove", onPointerMove);
      container.removeEventListener("click", onClick);
    };
  }, [onHover, onSelect]);

  return <div ref={containerRef} className="globe-scene cursor-crosshair" aria-label="airport globe" />;
});
