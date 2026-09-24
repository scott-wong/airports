import type { AirportType } from "../types";

export interface TypeStyle {
  color: string;
  size: number;
  labelKey: string;
}

export const TYPE_STYLE: Record<AirportType, TypeStyle> = {
  large_airport: { color: "#4de3ff", size: 5.4, labelKey: "types.large_airport" },
  medium_airport: { color: "#4aa8ff", size: 4.0, labelKey: "types.medium_airport" },
  small_airport: { color: "#2f6ea8", size: 2.6, labelKey: "types.small_airport" },
  heliport: { color: "#b980ff", size: 2.6, labelKey: "types.heliport" },
  seaplane_base: { color: "#4fe0b5", size: 2.8, labelKey: "types.seaplane_base" },
  balloonport: { color: "#ffb454", size: 3.0, labelKey: "types.balloonport" },
  closed: { color: "#ff5f6d", size: 2.4, labelKey: "types.closed" },
};

export function typeColor(type: AirportType): string {
  return (TYPE_STYLE[type] ?? TYPE_STYLE.small_airport).color;
}

export function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  const parsed = Number.parseInt(value.length === 3 ? value.replace(/(.)/g, "$1$1") : value, 16);
  return [((parsed >> 16) & 255) / 255, ((parsed >> 8) & 255) / 255, (parsed & 255) / 255];
}
