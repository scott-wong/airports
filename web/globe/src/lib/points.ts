import * as THREE from "three";

import type { Airport } from "../types";
import { TYPE_STYLE, hexToRgb } from "./colors";
import { latLngToVector3 } from "./geo";

/** 点相对球面的高度（球半径 100 单位，抬高 1.2 单位避免被球体深度遮挡）。 */
export const POINT_ALTITUDE = 0.012;

export const POINT_VERTEX = `
  uniform float uPixelRatio;
  attribute float aSize;
  attribute vec3 aColor;
  attribute float aPhase;
  varying vec3 vColor;
  varying float vPhase;
  void main() {
    vColor = aColor;
    vPhase = aPhase;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    float attenuation = 260.0 * uPixelRatio / max(-mv.z, 1.0);
    gl_PointSize = clamp(aSize * attenuation, 1.0, 64.0);
  }
`;

export const POINT_FRAGMENT = `
  uniform float uTime;
  varying vec3 vColor;
  varying float vPhase;
  void main() {
    vec2 uv = gl_PointCoord - vec2(0.5);
    float d = length(uv);
    if (d > 0.5) discard;
    float glow = smoothstep(0.5, 0.04, d);
    float core = smoothstep(0.2, 0.0, d);
    float pulse = 0.88 + 0.12 * sin(uTime * 1.6 + vPhase);
    vec3 color = vColor * (0.8 + core * 1.1);
    gl_FragColor = vec4(color, glow * pulse);
  }
`;

export function makePointsMaterial(): THREE.ShaderMaterial {
  const pixelRatio = typeof window === "undefined" ? 1 : Math.min(window.devicePixelRatio || 1, 2);
  return new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uPixelRatio: { value: pixelRatio } },
    vertexShader: POINT_VERTEX,
    fragmentShader: POINT_FRAGMENT,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
  });
}

/** 把机场列表压成单个 BufferGeometry（一次 draw call）。 */
export function buildGeometry(airports: Airport[]): THREE.BufferGeometry {
  const count = airports.length;
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  for (let index = 0; index < count; index += 1) {
    const airport = airports[index];
    const point = latLngToVector3(airport.lat, airport.lon, POINT_ALTITUDE);
    positions[index * 3] = point.x;
    positions[index * 3 + 1] = point.y;
    positions[index * 3 + 2] = point.z;
    const style = TYPE_STYLE[airport.type] ?? TYPE_STYLE.small_airport;
    const [r, g, b] = hexToRgb(style.color);
    colors[index * 3] = r;
    colors[index * 3 + 1] = g;
    colors[index * 3 + 2] = b;
    sizes[index] = style.size;
    phases[index] = ((airport.id % 100) / 100) * Math.PI * 2;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
  return geometry;
}

export function createStarfield(count = 1800): THREE.Points {
  const positions = new Float32Array(count * 3);
  for (let index = 0; index < count; index += 1) {
    const radius = 900 + Math.random() * 400;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
    positions[index * 3 + 1] = radius * Math.cos(phi);
    positions[index * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    color: 0x9fd8ff,
    size: 1.6,
    sizeAttenuation: false,
    transparent: true,
    opacity: 0.75,
    depthWrite: false,
  });
  return new THREE.Points(geometry, material);
}
