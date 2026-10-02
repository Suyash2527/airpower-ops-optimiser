"use client";

import {
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

// Neutral, sparsely populated region. Bases generated in Phase 1 are fictional
// and placed inside this box (see docs/DECISIONS.md D-12).
const DEFAULT_CENTER: [number, number] = [134, -25];
const DEFAULT_ZOOM = 5;

const OSM_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

// The worker is copied to /public by scripts/copy-maplibre-worker.mjs (bundler cannot resolve it).
const WORKER_URL = "/maplibre/maplibre-gl-worker.mjs";

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    setWorkerUrl(WORKER_URL);
    const map = new MapLibreMap({
      container: container.current,
      style: OSM_STYLE,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    });
    map.addControl(new NavigationControl(), "top-right");
    return () => map.remove();
  }, []);

  return (
    <div className="relative min-h-[480px] flex-1">
      <div className="absolute inset-0">
        <div ref={container} data-testid="cop-map" className="h-full w-full" />
      </div>
    </div>
  );
}
