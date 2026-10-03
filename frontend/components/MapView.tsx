"use client";

import { useState } from "react";
import type { Snapshot } from "@/lib/types";
import { tmin } from "@/components/ui";

// D-22: no tiles and no administrative boundaries. Points are placed by lat/lon on a plain
// equirectangular grid; the view always includes the India region and every plotted object.
const INDIA_BOX = { minLon: 68, maxLon: 97.5, minLat: 6.5, maxLat: 36 };
const WIDTH = 1000;
const KM_PER_DEG = 111.32;

type Layer = "bases" | "missions" | "threats" | "airspace" | "airfields";
const LAYERS: { key: Layer; label: string; swatch: string }[] = [
  { key: "bases", label: "Bases", swatch: "bg-sky-700" },
  { key: "missions", label: "Mission areas", swatch: "bg-emerald-500" },
  { key: "threats", label: "Threat zones", swatch: "bg-red-500" },
  { key: "airspace", label: "Airspace restrictions", swatch: "bg-violet-500" },
  { key: "airfields", label: "Alternate airfields (open data)", swatch: "bg-slate-400" },
];

function extent(s: Snapshot) {
  const lons = [INDIA_BOX.minLon, INDIA_BOX.maxLon];
  const lats = [INDIA_BOX.minLat, INDIA_BOX.maxLat];
  const add = (lat: number, lon: number) => {
    lats.push(lat);
    lons.push(lon);
  };
  s.bases.forEach((b) => add(b.lat, b.lon));
  s.missions.forEach((m) => add(m.aoi.center.lat, m.aoi.center.lon));
  s.threats.forEach((t) => add(t.center.lat, t.center.lon));
  s.airspace.forEach((z) => z.polygon.coordinates[0].forEach(([lon, lat]) => add(lat, lon)));
  const pad = 1.5;
  return {
    minLon: Math.min(...lons) - pad,
    maxLon: Math.max(...lons) + pad,
    minLat: Math.min(...lats) - pad,
    maxLat: Math.max(...lats) + pad,
  };
}

export default function MapView({ snapshot, height = 560 }: { snapshot: Snapshot; height?: number }) {
  const [shown, setShown] = useState<Record<Layer, boolean>>({
    bases: true,
    missions: true,
    threats: true,
    airspace: true,
    airfields: false,
  });
  const [hover, setHover] = useState<string | null>(null);

  const e = extent(snapshot);
  const k = Math.cos((((e.minLat + e.maxLat) / 2) * Math.PI) / 180); // shrink longitude at mid-latitude
  const scale = WIDTH / ((e.maxLon - e.minLon) * k);
  const h = (e.maxLat - e.minLat) * scale;
  const x = (lon: number) => (lon - e.minLon) * k * scale;
  const y = (lat: number) => (e.maxLat - lat) * scale;
  const r = (km: number) => (km / KM_PER_DEG) * scale;

  const grid: number[] = [];
  for (let g = -180; g <= 180; g += 5) grid.push(g);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {LAYERS.map((l) => (
          <label key={l.key} className="flex cursor-pointer items-center gap-1.5 text-slate-700">
            <input type="checkbox" checked={shown[l.key]} onChange={() => setShown({ ...shown, [l.key]: !shown[l.key] })} />
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${l.swatch}`} />
            {l.label}
          </label>
        ))}
      </div>
      <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
        <svg viewBox={`0 0 ${WIDTH} ${h}`} style={{ maxHeight: height }} className="block h-auto w-full" data-testid="cop-map">
          {grid.filter((g) => g > e.minLon && g < e.maxLon).map((g) => (
            <g key={`lon${g}`}>
              <line x1={x(g)} x2={x(g)} y1={0} y2={h} stroke="#cbd5e1" strokeWidth={1} />
              <text x={x(g) + 3} y={h - 4} fontSize={11} fill="#64748b">{g}°E</text>
            </g>
          ))}
          {grid.filter((g) => g > e.minLat && g < e.maxLat).map((g) => (
            <g key={`lat${g}`}>
              <line y1={y(g)} y2={y(g)} x1={0} x2={WIDTH} stroke="#cbd5e1" strokeWidth={1} />
              <text x={4} y={y(g) - 3} fontSize={11} fill="#64748b">{g}°N</text>
            </g>
          ))}

          {shown.airspace && snapshot.airspace.map((z) => (
            <polygon
              key={z.id}
              points={z.polygon.coordinates[0].map(([lon, lat]) => `${x(lon)},${y(lat)}`).join(" ")}
              fill="rgb(139 92 246 / 0.12)"
              stroke="rgb(124 58 237)"
              strokeDasharray="5 3"
              strokeWidth={1.5}
              onMouseEnter={() => setHover(`${z.id} · ${z.kind} · active ${tmin(z.active_from_min)} to ${tmin(z.active_to_min)}`)}
              onMouseLeave={() => setHover(null)}
            />
          ))}
          {shown.threats && snapshot.threats.map((t) => (
            <circle
              key={t.id}
              cx={x(t.center.lon)}
              cy={y(t.center.lat)}
              r={Math.max(r(t.radius_km), 3)}
              fill={`rgb(239 68 68 / ${0.1 + t.severity * 0.25})`}
              stroke="rgb(220 38 38)"
              strokeWidth={1.5}
              onMouseEnter={() => setHover(`${t.id} · ${t.type} · radius ${t.radius_km.toFixed(0)} km · severity ${t.severity.toFixed(2)} · active ${tmin(t.active_from_min)} to ${tmin(t.active_to_min)}`)}
              onMouseLeave={() => setHover(null)}
            />
          ))}
          {shown.missions && snapshot.missions.map((m) => (
            <circle
              key={m.id}
              cx={x(m.aoi.center.lon)}
              cy={y(m.aoi.center.lat)}
              r={Math.max(r(m.aoi.radius_km), 4)}
              fill="rgb(16 185 129 / 0.25)"
              stroke="rgb(5 150 105)"
              strokeWidth={1.2}
              onMouseEnter={() => setHover(`${m.id} · ${m.capability_required} · priority ${m.priority} · window ${tmin(m.window_start_min)} to ${tmin(m.window_end_min)}`)}
              onMouseLeave={() => setHover(null)}
            />
          ))}
          {shown.airfields && snapshot.alternate_airfields.map((a) => (
            <circle
              key={a.id}
              cx={x(a.lon)}
              cy={y(a.lat)}
              r={3.5}
              fill="#94a3b8"
              onMouseEnter={() => setHover(`${a.name} · alternate airfield · source ${a.provenance.source} (open data)`)}
              onMouseLeave={() => setHover(null)}
            />
          ))}
          {shown.bases && snapshot.bases.map((b) => (
            <g
              key={b.id}
              onMouseEnter={() => setHover(`${b.name} · ${b.region} · ${b.runways} runway(s) · fictional base`)}
              onMouseLeave={() => setHover(null)}
            >
              <rect x={x(b.lon) - 7} y={y(b.lat) - 7} width={14} height={14} rx={2} fill="#0369a1" stroke="white" strokeWidth={2} />
              <text x={x(b.lon) + 11} y={y(b.lat) + 4} fontSize={13} fontWeight={600} fill="#0c4a6e">{b.name}</text>
            </g>
          ))}
        </svg>
        <p className="absolute bottom-2 left-2 max-w-[90%] rounded bg-white/90 px-2 py-1 text-xs text-slate-600 shadow-sm">
          Position grid only: no boundaries are drawn. Boundaries are not authoritative.
        </p>
        <p className="absolute right-2 top-2 rounded bg-white/90 px-2 py-1 text-xs text-slate-700 shadow-sm" aria-live="polite">
          {hover ?? "Hover a shape for details"}
        </p>
      </div>
    </div>
  );
}
