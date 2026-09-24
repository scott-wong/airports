import { useCallback, useEffect, useImperativeHandle, useRef, forwardRef } from "react";
import Globe, { type GlobeInstance } from "globe.gl";
import * as THREE from "three";

import {
  type BorderLevel,
  createBorderLines,
  fetchBorderPayload,
  isFinerThan,
  levelForDistance,
} from "../lib/borders";
import { GLOBE_RADIUS, latLngToVector3 } from "../lib/geo";
import { POINT_ALTITUDE, buildGeometry, createStarfield, makePointsMaterial } from "../lib/points";
import { buildPickGrid, candidatesNear, pickNearest, type PickGrid } from "../lib/picking";
import type { Airport } from "../types";

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
  onDetailLevel?: (level: BorderLevel) => void;
}

/** 拉远时只保留这些类型，避免 8.6 万点糊成一团（见 ADR-0002）。 */
const COARSE_TYPES = new Set(["large_airport", "medium_airport", "seaplane_base", "balloonport"]);
const COARSE_DISTANCE = 380;

export const GlobeView = forwardRef<GlobeHandle, GlobeProps>(function GlobeView(
  { airports, selected, onHover, onSelect, autoRotate, borders, onDetailLevel },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<GlobeInstance | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  const markerRef = useRef<THREE.Points | null>(null);
  const airportsRef = useRef<Airport[]>(airports);
  const gridRef = useRef<PickGrid | null>(null);
  const coarseRef = useRef(false);
  const borderLevelRef = useRef<BorderLevel | null>(null);
  const borderLinesRef = useRef<THREE.LineSegments | null>(null);
  const borderRequestRef = useRef<BorderLevel | null>(null);
  const detailLevelCallbackRef = useRef(onDetailLevel);
  const idleTimerRef = useRef<number | null>(null);
  const autoRotateRef = useRef(autoRotate);

  const rebuildPoints = useCallback((list: Airport[], coarse: boolean) => {
    const points = pointsRef.current;
    if (!points) return;
    const rendered = coarse ? list.filter((airport) => COARSE_TYPES.has(airport.type)) : list;
    const previous = points.geometry;
    points.geometry = buildGeometry(rendered);
    previous?.dispose();
    // 拾取必须针对“真正画出来的那批点”，否则抽稀后下标会错位。
    airportsRef.current = rendered;
    gridRef.current = buildPickGrid(rendered);
  }, []);

  /** 按需加载国界层级；只会向更细的方向升级，避免来回抖动。 */
  const ensureBorderLevel = useCallback(
    (level: BorderLevel) => {
      const globe = globeRef.current;
      if (!globe) return;
      if (!isFinerThan(level, borderLevelRef.current) || borderRequestRef.current === level) return;
      borderRequestRef.current = level;
      void fetchBorderPayload(level)
        .then((payload) => {
          const activeGlobe = globeRef.current;
          if (!activeGlobe) return;
          const lines = createBorderLines(payload, level === "coarse" ? 0.4 : 0.3);
          if (borderLinesRef.current) {
            activeGlobe.scene().remove(borderLinesRef.current);
            borderLinesRef.current.geometry.dispose();
            (borderLinesRef.current.material as THREE.Material).dispose();
          }
          activeGlobe.scene().add(lines);
          borderLinesRef.current = lines;
          borderLevelRef.current = level;
          detailLevelCallbackRef.current?.(level);
        })
        .catch((error: unknown) => {
          console.warn("国界加载失败", error);
        })
        .finally(() => {
          if (borderRequestRef.current === level) borderRequestRef.current = null;
        });
    },
    [],
  );

  const applyView = useCallback(
    (airport: Airport) => {
      globeRef.current?.pointOfView(
        { lat: airport.lat, lng: airport.lon, altitude: 0.55 },
        900,
      );
    },
    [],
  );

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
    controls.minDistance = GLOBE_RADIUS * 1.12;
    controls.maxDistance = GLOBE_RADIUS * 6;

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

    const light = new THREE.AmbientLight(0x6688aa, 1.1);
    globe.scene().add(light);

    globeRef.current = globe;
    (window as unknown as { __airportGlobe?: GlobeInstance }).__airportGlobe = globe;
    ensureBorderLevel(levelForDistance(globe.camera().position.length()));

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
        ensureBorderLevel(levelForDistance(distance));
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
      if (borderLinesRef.current) {
        globe.scene().remove(borderLinesRef.current);
        borderLinesRef.current.geometry.dispose();
        (borderLinesRef.current.material as THREE.Material).dispose();
        borderLinesRef.current = null;
        borderLevelRef.current = null;
      }
      points.geometry.dispose();
      (points.material as THREE.Material).dispose();
      marker.geometry.dispose();
      (marker.material as THREE.Material).dispose();
      globeRef.current = null;
      pointsRef.current = null;
      markerRef.current = null;
    };
  }, [rebuildPoints, ensureBorderLevel]);

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
    const globe = globeRef.current;
    const lines = borderLinesRef.current;
    if (!globe || !lines) return;
    lines.visible = borders;
  }, [borders]);

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
      const camera = globe.camera();
      const cameraPosition = camera.position;
      const project = (airport: Airport) => {
        const world = latLngToVector3(airport.lat, airport.lon, POINT_ALTITUDE);
        const facing =
          world.x * cameraPosition.x + world.y * cameraPosition.y + world.z * cameraPosition.z;
        if (facing < GLOBE_RADIUS * GLOBE_RADIUS * 0.92) return null;
        const screen = globe.getScreenCoords(airport.lat, airport.lon, POINT_ALTITUDE);
        return { x: screen.x, y: screen.y };
      };
      for (const rings of [1, 2, 4]) {
        const candidates = candidatesNear(grid, geo.lat, geo.lng, rings);
        const hit = pickNearest(candidates, list, project, cursor, 12);
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
      const project = (airport: Airport) => {
        const world = latLngToVector3(airport.lat, airport.lon, POINT_ALTITUDE);
        const facing =
          world.x * cameraPosition.x + world.y * cameraPosition.y + world.z * cameraPosition.z;
        if (facing < GLOBE_RADIUS * GLOBE_RADIUS * 0.92) return null;
        const screen = globe.getScreenCoords(airport.lat, airport.lon, POINT_ALTITUDE);
        return { x: screen.x, y: screen.y };
      };
      for (const rings of [1, 2, 4]) {
        const candidates = candidatesNear(grid, geo.lat, geo.lng, rings);
        const hit = pickNearest(candidates, list, project, cursor, 14);
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
