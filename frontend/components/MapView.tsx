"use client";

import { useEffect, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import type { Assignment, Snapshot } from "@/lib/types";
import { Button, tmin } from "@/components/ui";

// D-22 / D-64: no tiles. Land comes from Natural Earth's India point-of-view countries file
// (public domain), simplified by scripts/build_india_outline.py. Equirectangular projection.
const REGION_BOX = { minLon: 55, maxLon: 120, minLat: -2, maxLat: 42 };
const INDIA_BOX = { minLon: 67, maxLon: 98, minLat: 6, maxLat: 37.5 };
const GEO_URL = "/geo/india_region.geojson";
// Neighbours worth labelling; others are drawn but unlabelled.
const LABELLED = new Set(["IND", "PAK", "CHN", "NPL", "BTN", "BGD", "MMR", "LKA", "AFG"]);

interface GeoFeature {
  properties: { name: string; iso: string };
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: number[][][] | number[][][][] };
}
const WIDTH = 1000;
const KM_PER_DEG = 111.32;

type Layer = "bases" | "missions" | "threats" | "airspace" | "routes" | "airfields";
const LAYERS: { key: Layer; label: string; swatch: string }[] = [
  { key: "bases", label: "Bases", swatch: "bg-sky-700" },
  { key: "missions", label: "Mission areas", swatch: "bg-emerald-500" },
  { key: "threats", label: "Threat zones", swatch: "bg-red-500" },
  { key: "airspace", label: "Airspace restrictions", swatch: "bg-violet-500" },
  { key: "routes", label: "Planned sorties", swatch: "bg-amber-500" },
  { key: "airfields", label: "Alternate airfields (open data)", swatch: "bg-slate-400" },
];

interface Selected {
  title: string;
  rows: [string, string][];
}

function extent(s: Snapshot) {
  const lons = [REGION_BOX.minLon, REGION_BOX.maxLon];
  const lats = [REGION_BOX.minLat, REGION_BOX.maxLat];
  const add = (lat: number, lon: number) => {
    lats.push(lat);
    lons.push(lon);
  };
  s.bases.forEach((b) => add(b.lat, b.lon));
  s.missions.forEach((m) => add(m.aoi.center.lat, m.aoi.center.lon));
  s.threats.forEach((t) => add(t.center.lat, t.center.lon));
  s.airspace.forEach((z) => z.polygon.coordinates[0].forEach(([lon, lat]) => add(lat, lon)));
  const pad = 0.5;
  return {
    minLon: Math.min(...lons) - pad,
    maxLon: Math.max(...lons) + pad,
    minLat: Math.min(...lats) - pad,
    maxLat: Math.max(...lats) + pad,
  };
}

const active = (t: number, from: number, to: number) => t >= from && t <= to;

export default function MapView({
  snapshot,
  assignments = [],
  planLabel,
}: {
  snapshot: Snapshot;
  assignments?: Assignment[];
  planLabel?: string;
}) {
  const [shown, setShown] = useState<Record<Layer, boolean>>({
    bases: true,
    missions: true,
    threats: true,
    airspace: true,
    routes: true,
    airfields: false,
  });
  const [t, setT] = useState(0);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [geo, setGeo] = useState<GeoFeature[] | null>(null);
  const [geoError, setGeoError] = useState(false);
  useEffect(() => {
    let live = true;
    fetch(GEO_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: { features: GeoFeature[] }) => live && setGeo(d.features))
      .catch(() => live && setGeoError(true));
    return () => {
      live = false;
    };
  }, []);

  const e = extent(snapshot);
  const k = Math.cos((((e.minLat + e.maxLat) / 2) * Math.PI) / 180); // shrink longitude at mid-latitude
  const scale = WIDTH / ((e.maxLon - e.minLon) * k);
  const H = (e.maxLat - e.minLat) * scale;
  const x = (lon: number) => (lon - e.minLon) * k * scale;
  const y = (lat: number) => (e.maxLat - lat) * scale;
  const r = (km: number) => (km / KM_PER_DEG) * scale;
  const horizon = snapshot.scenario.horizon_min;

  // View box in SVG units: zoom with the wheel or buttons, pan by dragging.
  const full = { x: 0, y: 0, w: WIDTH, h: H };
  // Fit the India box while keeping the canvas aspect ratio.
  const fit = (b: typeof INDIA_BOX) => {
    const bw = x(b.maxLon) - x(b.minLon);
    const bh = y(b.minLat) - y(b.maxLat);
    const w = Math.max(bw, (bh * WIDTH) / H);
    const h = (w * H) / WIDTH;
    return { x: (x(b.minLon) + x(b.maxLon)) / 2 - w / 2, y: (y(b.maxLat) + y(b.minLat)) / 2 - h / 2, w, h };
  };
  const india = fit(INDIA_BOX);
  const [view, setView] = useState(india);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ px: number; py: number; vx: number; vy: number; moved: boolean } | null>(null);
  // React wheel listeners are passive, so stop the page scrolling under the map natively.
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const stop = (ev: globalThis.WheelEvent) => ev.preventDefault();
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, []);
  const z = view.w / WIDTH; // < 1 when zoomed in; keeps labels and markers a constant screen size

  const toSvg = (clientX: number, clientY: number) => {
    const rect = svg.current!.getBoundingClientRect();
    return { sx: view.x + ((clientX - rect.left) / rect.width) * view.w, sy: view.y + ((clientY - rect.top) / rect.height) * view.h, rect };
  };
  const zoomAt = (factor: number, sx: number, sy: number) =>
    setView((v) => {
      const w = Math.min(WIDTH, Math.max(WIDTH / 20, v.w * factor));
      const f = w / v.w;
      return { x: sx - (sx - v.x) * f, y: sy - (sy - v.y) * f, w, h: v.h * f };
    });
  const onWheel = (ev: WheelEvent<SVGSVGElement>) => {
    const { sx, sy } = toSvg(ev.clientX, ev.clientY);
    zoomAt(ev.deltaY < 0 ? 0.8 : 1.25, sx, sy);
  };
  const onDown = (ev: PointerEvent<SVGSVGElement>) => {
    drag.current = { px: ev.clientX, py: ev.clientY, vx: view.x, vy: view.y, moved: false };
  };
  const onMove = (ev: PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d) return;
    const rect = svg.current!.getBoundingClientRect();
    const dx = ((ev.clientX - d.px) / rect.width) * view.w;
    const dy = ((ev.clientY - d.py) / rect.height) * view.h;
    if (Math.abs(ev.clientX - d.px) + Math.abs(ev.clientY - d.py) > 3) {
      d.moved = true;
      svg.current!.setPointerCapture(ev.pointerId);
    }
    if (d.moved) setView((v) => ({ ...v, x: d.vx - dx, y: d.vy - dy }));
  };
  const wasDrag = useRef(false);
  const onUp = () => {
    wasDrag.current = drag.current?.moved ?? false;
    drag.current = null;
  };
  const pick = (s: Selected) => () => {
    if (!wasDrag.current) setSelected(s);
  };

  const ringPath = (ring: number[][]) => ring.map(([lon, lat], i) => `${i ? "L" : "M"}${x(lon).toFixed(1)},${y(lat).toFixed(1)}`).join("") + "Z";
  const land = (geo ?? []).map((f) => {
    const polys = (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates) as number[][][][];
    const d = polys.map((p) => p.map(ringPath).join("")).join("");
    // Label at the centre of the largest polygon's outer ring.
    const outer = polys.map((p) => p[0]).sort((a, b) => b.length - a.length)[0] ?? [];
    const lon = outer.reduce((acc, c) => acc + c[0], 0) / Math.max(outer.length, 1);
    const lat = outer.reduce((acc, c) => acc + c[1], 0) / Math.max(outer.length, 1);
    return { iso: f.properties.iso, name: f.properties.name, d, lx: x(lon), ly: y(lat) };
  });

  const grid: number[] = [];
  const step = z > 0.5 ? 5 : z > 0.2 ? 2 : 1;
  for (let g = -180; g <= 180; g += step) grid.push(g);
  const fs = (px: number) => px * z * (WIDTH / 900);
  const baseById = new Map(snapshot.bases.map((b) => [b.id, b]));
  const airborne = assignments.filter((a) => active(t, a.takeoff_min, a.land_min));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {LAYERS.map((l) => (
          <label key={l.key} className="flex cursor-pointer items-center gap-1.5 text-slate-700">
            <input type="checkbox" checked={shown[l.key]} onChange={() => setShown({ ...shown, [l.key]: !shown[l.key] })} />
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${l.swatch}`} />
            {l.label}
          </label>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
        <span className="font-medium text-slate-700">Time</span>
        <input
          type="range"
          min={0}
          max={horizon}
          step={15}
          value={t}
          onChange={(ev) => setT(Number(ev.target.value))}
          className="min-w-40 flex-1 accent-sky-700"
          aria-label="Scenario time"
        />
        <span className="w-20 font-mono tabular-nums text-slate-900">{tmin(t)}</span>
        <span className="text-xs text-slate-500">
          {snapshot.threats.filter((th) => active(t, th.active_from_min, th.active_to_min)).length} threat zone(s) active ·{" "}
          {airborne.length} sortie(s) airborne{planLabel ? ` (${planLabel})` : ""}
        </span>
      </div>

      <div className="relative">
        <div className="relative overflow-hidden rounded-lg border border-slate-300 bg-[#dbeafe]">
          <svg
            ref={svg}
            viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
            className="block h-auto w-full cursor-grab touch-none select-none active:cursor-grabbing"
            style={{ aspectRatio: `${WIDTH} / ${H}` }}
            data-testid="cop-map"
            onWheel={onWheel}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
          >
            <rect x={-WIDTH} y={-H} width={WIDTH * 3} height={H * 3} fill="#dbeafe" />
            {land.map((c) => (
              <path
                key={c.iso + c.name}
                d={c.d}
                fill={c.iso === "IND" ? "#fefce8" : "#e5e7eb"}
                stroke={c.iso === "IND" ? "#78716c" : "#9ca3af"}
                strokeWidth={c.iso === "IND" ? 1.4 : 0.8}
                vectorEffect="non-scaling-stroke"
                fillRule="evenodd"
              />
            ))}
            {grid.filter((g) => g > e.minLon && g < e.maxLon).map((g) => (
              <g key={`lon${g}`}>
                <line x1={x(g)} x2={x(g)} y1={0} y2={H} stroke="#94a3b8" strokeOpacity={0.35} strokeWidth={1} vectorEffect="non-scaling-stroke" />
                <text x={x(g) + fs(3)} y={view.y + view.h - fs(5)} fontSize={fs(11)} fill="#64748b">{g}°E</text>
              </g>
            ))}
            {grid.filter((g) => g > e.minLat && g < e.maxLat).map((g) => (
              <g key={`lat${g}`}>
                <line y1={y(g)} y2={y(g)} x1={0} x2={WIDTH} stroke="#94a3b8" strokeOpacity={0.35} strokeWidth={1} vectorEffect="non-scaling-stroke" />
                <text x={view.x + fs(4)} y={y(g) - fs(3)} fontSize={fs(11)} fill="#64748b">{g}°N</text>
              </g>
            ))}

            {shown.airspace && snapshot.airspace.map((zn) => {
              const on = active(t, zn.active_from_min, zn.active_to_min);
              return (
                <polygon
                  key={zn.id}
                  className="cursor-pointer"
                  points={zn.polygon.coordinates[0].map(([lon, lat]) => `${x(lon)},${y(lat)}`).join(" ")}
                  fill={on ? "rgb(139 92 246 / 0.18)" : "rgb(139 92 246 / 0.04)"}
                  stroke="rgb(124 58 237)"
                  strokeOpacity={on ? 1 : 0.35}
                  strokeDasharray="5 3"
                  strokeWidth={1.5}
                  vectorEffect="non-scaling-stroke"
                  onClick={pick({
                    title: `${zn.id} · airspace`,
                    rows: [["Kind", zn.kind], ["Active", `${tmin(zn.active_from_min)} to ${tmin(zn.active_to_min)}`], ["At current time", on ? "active" : "inactive"]],
                  })}
                />
              );
            })}

            {shown.threats && snapshot.threats.map((th) => {
              const on = active(t, th.active_from_min, th.active_to_min);
              return (
                <circle
                  key={th.id}
                  className="cursor-pointer"
                  cx={x(th.center.lon)}
                  cy={y(th.center.lat)}
                  r={Math.max(r(th.radius_km), fs(3))}
                  fill={on ? `rgb(239 68 68 / ${0.12 + th.severity * 0.3})` : "rgb(239 68 68 / 0.04)"}
                  stroke="rgb(220 38 38)"
                  strokeOpacity={on ? 1 : 0.3}
                  strokeDasharray={on ? undefined : "4 3"}
                  strokeWidth={1.5}
                  vectorEffect="non-scaling-stroke"
                  onClick={pick({
                    title: `${th.id} · threat zone`,
                    rows: [
                      ["Type", th.type],
                      ["Radius", `${th.radius_km.toFixed(0)} km`],
                      ["Severity", th.severity.toFixed(2)],
                      ["Active", `${tmin(th.active_from_min)} to ${tmin(th.active_to_min)}`],
                      ["At current time", on ? "active" : "inactive"],
                    ],
                  })}
                />
              );
            })}

            {shown.missions && snapshot.missions.map((m) => {
              const on = active(t, m.window_start_min, m.window_end_min);
              const covered = assignments.filter((a) => a.mission_id === m.id);
              return (
                <circle
                  key={m.id}
                  className="cursor-pointer"
                  cx={x(m.aoi.center.lon)}
                  cy={y(m.aoi.center.lat)}
                  r={Math.max(r(m.aoi.radius_km), fs(4))}
                  fill={covered.length ? "rgb(16 185 129 / 0.3)" : "rgb(255 255 255 / 0.6)"}
                  stroke="rgb(5 150 105)"
                  strokeOpacity={on ? 1 : 0.45}
                  strokeWidth={on ? 2.2 : 1.2}
                  vectorEffect="non-scaling-stroke"
                  onClick={pick({
                    title: `${m.id} · ${m.name}`,
                    rows: [
                      ["Capability", m.capability_required],
                      ["Priority", String(m.priority)],
                      ["Window", `${tmin(m.window_start_min)} to ${tmin(m.window_end_min)}`],
                      ["Area radius", `${m.aoi.radius_km.toFixed(0)} km`],
                      ["In plan", covered.length ? covered.map((a) => `${a.aircraft_id} ${tmin(a.takeoff_min)}`).join(", ") : planLabel ? "not assigned" : "no plan loaded"],
                    ],
                  })}
                />
              );
            })}

            {shown.routes && assignments.map((a) => {
              const b = baseById.get(a.base_from);
              const m = snapshot.missions.find((mm) => mm.id === a.mission_id);
              if (!b || !m) return null;
              const flying = active(t, a.takeoff_min, a.land_min);
              return (
                <line
                  key={a.id}
                  className="cursor-pointer"
                  x1={x(b.lon)}
                  y1={y(b.lat)}
                  x2={x(m.aoi.center.lon)}
                  y2={y(m.aoi.center.lat)}
                  stroke={flying ? "rgb(217 119 6)" : "rgb(245 158 11)"}
                  strokeOpacity={flying ? 1 : 0.35}
                  strokeWidth={flying ? 3 : 1.3}
                  vectorEffect="non-scaling-stroke"
                  onClick={pick({
                    title: `Sortie ${a.id}`,
                    rows: [
                      ["Mission", a.mission_id],
                      ["Aircraft", a.aircraft_id],
                      ["From", a.base_from],
                      ["Take-off / land", `${tmin(a.takeoff_min)} / ${tmin(a.land_min)}`],
                      ["Crew", a.crew_ids.join(", ")],
                      ["Risk (total)", a.risk.total.toFixed(2)],
                    ],
                  })}
                />
              );
            })}

            {shown.airfields && snapshot.alternate_airfields.map((a) => (
              <circle
                key={a.id}
                className="cursor-pointer"
                cx={x(a.lon)}
                cy={y(a.lat)}
                r={fs(3.5)}
                fill="#94a3b8"
                onClick={pick({ title: a.name, rows: [["Kind", "alternate airfield"], ["Source", `${a.provenance.source} (open data)`]] })}
              />
            ))}

            {land.filter((c) => LABELLED.has(c.iso)).map((c) => (
              <text
                key={`lbl${c.iso}`}
                x={c.lx}
                y={c.ly}
                textAnchor="middle"
                fontSize={fs(c.iso === "IND" ? 22 : 13)}
                fontWeight={c.iso === "IND" ? 700 : 500}
                letterSpacing={c.iso === "IND" ? fs(6) : 0}
                fill={c.iso === "IND" ? "#a8a29e" : "#9ca3af"}
                className="pointer-events-none uppercase"
              >
                {c.name}
              </text>
            ))}
            {shown.bases && snapshot.bases.map((b) => (
              <g
                key={b.id}
                className="cursor-pointer"
                onClick={pick({
                  title: `${b.name} · fictional base`,
                  rows: [
                    ["Region", b.region],
                    ["Elevation", `${Math.round(b.elevation_m * 3.28084).toLocaleString()} ft`],
                    ["Runways", String(b.runways)],
                    ["Aircraft based", String(snapshot.aircraft.filter((a) => a.base_id === b.id).length)],
                    ["Position", `${b.lat.toFixed(2)}°N ${b.lon.toFixed(2)}°E`],
                  ],
                })}
              >
                <rect x={x(b.lon) - fs(7)} y={y(b.lat) - fs(7)} width={fs(14)} height={fs(14)} rx={fs(2)} fill="#0369a1" stroke="white" strokeWidth={fs(2)} />
                <text x={x(b.lon) + fs(11)} y={y(b.lat) + fs(4)} fontSize={fs(13)} fontWeight={600} fill="#0c4a6e" stroke="white" strokeWidth={fs(3)} paintOrder="stroke">
                  {b.name}
                </text>
              </g>
            ))}
          </svg>

          <div className="absolute right-2 top-2 flex flex-col gap-1">
            <Button aria-label="Zoom in" className="h-8 w-8 !px-0" onClick={() => zoomAt(0.7, view.x + view.w / 2, view.y + view.h / 2)}>+</Button>
            <Button aria-label="Zoom out" className="h-8 w-8 !px-0" onClick={() => zoomAt(1 / 0.7, view.x + view.w / 2, view.y + view.h / 2)}>−</Button>
            <Button className="h-8 !px-2 text-xs" onClick={() => setView(india)} title="Zoom to India">India</Button>
            <Button className="h-8 !px-2 text-xs" onClick={() => setView(full)} title="Show every plotted object">All</Button>
          </div>
          <p className="absolute bottom-2 left-2 max-w-[90%] rounded bg-white/90 px-2 py-1 text-xs text-slate-600 shadow-sm">
            {geoError
              ? "Map outline could not be loaded; positions are shown on the grid only. "
              : "Outline: Natural Earth (public domain), India point of view, simplified. "}
            Boundaries are not authoritative. Scroll to zoom, drag to pan.
          </p>
        </div>

        {selected && (
          <aside className="absolute left-2 top-2 w-72 max-w-[calc(100%-6rem)] rounded-lg border border-slate-200 bg-white/95 p-3 text-sm shadow-md">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-semibold text-slate-900">{selected.title}</h3>
              <button className="text-xs text-slate-500 hover:text-slate-900" onClick={() => setSelected(null)}>Close</button>
            </div>
            <dl className="mt-2 divide-y divide-slate-100">
              {selected.rows.map(([k2, v]) => (
                <div key={k2} className="flex justify-between gap-3 py-1.5">
                  <dt className="text-slate-500">{k2}</dt>
                  <dd className="text-right font-medium text-slate-800">{v}</dd>
                </div>
              ))}
            </dl>
          </aside>
        )}
      </div>
      <p className="text-xs text-slate-600">
        <b>How to read it:</b> click any shape for details. Blue squares are (fictional) bases. Green circles are mission areas,
        filled when the plan covers them. Red circles are threat zones and purple dashed shapes are airspace restrictions; both are
        bold while active at the selected time. Orange lines are planned sorties, bold while airborne. Circle sizes match each
        zone&apos;s radius in km.
      </p>
    </div>
  );
}
