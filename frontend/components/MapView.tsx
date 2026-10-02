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

// D-22: no raster tiles and no vector boundaries. A plain background keeps
// administrative borders off the map until a verified GoI-compliant layer exists.
const NEUTRAL_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e4e7eb" } }],
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
      style: NEUTRAL_STYLE,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    });
    map.addControl(new NavigationControl(), "top-right");
    return () => map.remove();
  }, []);

  return (
    <div className="relative h-72">
      <div className="absolute inset-0">
        <div ref={container} data-testid="cop-map" className="h-full w-full" />
        <p className="absolute bottom-1 left-1 rounded bg-white/80 px-2 py-0.5 text-xs">
          Neutral basemap: no boundaries drawn. Boundaries are not authoritative.
        </p>
      </div>
    </div>
  );
}
