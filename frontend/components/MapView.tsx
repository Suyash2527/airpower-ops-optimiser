"use client";

import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode, type WheelEvent } from "react";
import type { Assignment, Snapshot } from "@/lib/types";
import { CAPABILITIES, REGIONS } from "@/lib/labels";
import { humanize, istAt, riskTone, tmin } from "@/lib/format";
import { Badge, Button, Card, DetailRows, Icon, IconButton, PriorityChip, Tooltip } from "@/components/ui";

// D-22 / D-64: no tiles. Land comes from Natural Earth's India point-of-view countries file
// (public domain), simplified by scripts/build_india_outline.py. Equirectangular projection.
const REGION_BOX = { minLon: 55, maxLon: 120, minLat: -2, maxLat: 42 };
const INDIA_BOX = { minLon: 67, maxLon: 98, minLat: 6, maxLat: 37.5 };
const GEO_URL = "/geo/india_region.geojson";
const LABELLED = new Set(["IND", "PAK", "CHN", "NPL", "BTN", "BGD", "MMR", "LKA", "AFG"]);
const WIDTH = 1000;
const KM_PER_DEG = 111.32;

interface GeoFeature {
  properties: { name: string; iso: string };
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: number[][][] | number[][][][] };
}

type Layer = "bases" | "missions" | "threats" | "airspace" | "routes" | "airfields";
interface Info {
  key: string;
  kind: string;
  title: ReactNode;
  subtitle?: ReactNode;
  rows: [ReactNode, ReactNode][];
}

const active = (t: number, from: number, to: number) => t >= from && t <= to;
const pColor = (p: number) => `var(--color-p${Math.min(5, Math.max(1, p))})`;

function extent(s: Snapshot) {
  const lons = [REGION_BOX.minLon, REGION_BOX.maxLon];
  const lats = [REGION_BOX.minLat, REGION_BOX.maxLat];
  const add = (lat: number, lon: number) => { lats.push(lat); lons.push(lon); };
  s.bases.forEach((b) => add(b.lat, b.lon));
  s.missions.forEach((m) => add(m.aoi.center.lat, m.aoi.center.lon));
  s.threats.forEach((t) => add(t.center.lat, t.center.lon));
  s.airspace.forEach((z) => z.polygon.coordinates[0].forEach(([lon, lat]) => add(lat, lon)));
  return { minLon: Math.min(...lons) - 0.5, maxLon: Math.max(...lons) + 0.5, minLat: Math.min(...lats) - 0.5, maxLat: Math.max(...lats) + 0.5 };
}

export default function MapView({ snapshot, assignments = [], planLabel }: { snapshot: Snapshot; assignments?: Assignment[]; planLabel?: string }) {
  const [shown, setShown] = useState<Record<Layer, boolean>>({ bases: true, missions: true, threats: true, airspace: true, routes: true, airfields: false });
  const [t, setT] = useState(0);
  const [selected, setSelected] = useState<Info | null>(null);
  const [hover, setHover] = useState<{ info: Info; x: number; y: number } | null>(null);
  const [geo, setGeo] = useState<GeoFeature[] | null>(null);
  const [geoError, setGeoError] = useState(false);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);

  useEffect(() => {
    let live = true;
    fetch(GEO_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: { features: GeoFeature[] }) => live && setGeo(d.features))
      .catch(() => live && setGeoError(true));
    return () => { live = false; };
  }, []);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width, h: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // React wheel listeners are passive, so stop the page scrolling under the map natively.
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const stop = (ev: globalThis.WheelEvent) => ev.preventDefault();
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, []);

  const e = extent(snapshot);
  const k = Math.cos((((e.minLat + e.maxLat) / 2) * Math.PI) / 180);
  const scale = WIDTH / ((e.maxLon - e.minLon) * k);
  const H = (e.maxLat - e.minLat) * scale;
  const x = (lon: number) => (lon - e.minLon) * k * scale;
  const y = (lat: number) => (e.maxLat - lat) * scale;
  const r = (km: number) => (km / KM_PER_DEG) * scale;
  const horizon = snapshot.scenario.horizon_min;
  const aspect = size ? size.h / Math.max(1, size.w) : 0.62;

  const fit = (b: typeof INDIA_BOX) => {
    const bw = x(b.maxLon) - x(b.minLon);
    const bh = y(b.minLat) - y(b.maxLat);
    const w = Math.max(bw, bh / aspect) * 1.04;
    return { cx: (x(b.minLon) + x(b.maxLon)) / 2, cy: (y(b.maxLat) + y(b.minLat)) / 2, w };
  };
  const all = { cx: WIDTH / 2, cy: H / 2, w: Math.max(WIDTH, H / aspect) };
  const [cam, setCam] = useState<{ cx: number; cy: number; w: number } | null>(null);
  const c = cam ?? fit(INDIA_BOX);
  const view = { x: c.cx - c.w / 2, y: c.cy - (c.w * aspect) / 2, w: c.w, h: c.w * aspect };
  const px = size ? view.w / size.w : view.w / 1000; // one screen pixel in SVG units
  const fs = (n: number) => n * px;

  const toSvg = (clientX: number, clientY: number) => {
    const rect = svg.current!.getBoundingClientRect();
    return { sx: view.x + ((clientX - rect.left) / rect.width) * view.w, sy: view.y + ((clientY - rect.top) / rect.height) * view.h };
  };
  const zoomAt = (factor: number, sx: number, sy: number) => {
    const w = Math.min(all.w * 1.2, Math.max(WIDTH / 30, c.w * factor));
    const f = w / c.w;
    setCam({ cx: sx - (sx - c.cx) * f, cy: sy - (sy - c.cy) * f, w });
  };
  const onWheel = (ev: WheelEvent<SVGSVGElement>) => {
    const { sx, sy } = toSvg(ev.clientX, ev.clientY);
    zoomAt(ev.deltaY < 0 ? 0.8 : 1.25, sx, sy);
  };
  const drag = useRef<{ px: number; py: number; cx: number; cy: number; moved: boolean } | null>(null);
  const wasDrag = useRef(false);
  const onDown = (ev: RPointerEvent<SVGSVGElement>) => { drag.current = { px: ev.clientX, py: ev.clientY, cx: c.cx, cy: c.cy, moved: false }; };
  const onMove = (ev: RPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d) return;
    if (Math.abs(ev.clientX - d.px) + Math.abs(ev.clientY - d.py) > 3 && !d.moved) {
      d.moved = true;
      svg.current!.setPointerCapture(ev.pointerId);
      setHover(null);
    }
    if (d.moved) setCam({ cx: d.cx - (ev.clientX - d.px) * px, cy: d.cy - (ev.clientY - d.py) * px, w: c.w });
  };
  const onUp = () => { wasDrag.current = drag.current?.moved ?? false; drag.current = null; };

  // Hover and click handlers for any plotted object.
  const bind = (info: Info) => ({
    onPointerEnter: (ev: RPointerEvent) => !drag.current?.moved && place(info, ev),
    onPointerMove: (ev: RPointerEvent) => !drag.current?.moved && place(info, ev),
    onPointerLeave: () => setHover(null),
    onClick: () => { if (!wasDrag.current) setSelected(info); },
    "data-hit": true,
  });
  const place = (info: Info, ev: RPointerEvent) => {
    const rect = box.current!.getBoundingClientRect();
    setHover({ info, x: ev.clientX - rect.left, y: ev.clientY - rect.top });
  };

  const ringPath = (ring: number[][]) => ring.map(([lon, lat], i) => `${i ? "L" : "M"}${x(lon).toFixed(1)},${y(lat).toFixed(1)}`).join("") + "Z";
  const land = (geo ?? []).map((f) => {
    const polys = (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates) as number[][][][];
    const d = polys.map((p) => p.map(ringPath).join("")).join("");
    const outer = polys.map((p) => p[0]).sort((a, b) => b.length - a.length)[0] ?? [];
    const lon = outer.reduce((acc, q) => acc + q[0], 0) / Math.max(outer.length, 1);
    const lat = outer.reduce((acc, q) => acc + q[1], 0) / Math.max(outer.length, 1);
    return { iso: f.properties.iso, name: f.properties.name, d, lx: x(lon), ly: y(lat) };
  });

  const grid: number[] = [];
  // Grid spacing in screen pixels, so labels never crowd on a phone or spread thin on a 4K screen.
  const pxPerDeg = (k * scale) / px;
  const step = [1, 2, 5, 10].find((d) => d * pxPerDeg >= 80) ?? 10;
  for (let g = -180; g <= 180; g += step) grid.push(g);
  const baseById = new Map(snapshot.bases.map((b) => [b.id, b]));
  const missionById = new Map(snapshot.missions.map((m) => [m.id, m]));
  const airborne = assignments.filter((a) => active(t, a.takeoff_min, a.land_min));
  const threatsOn = snapshot.threats.filter((th) => active(t, th.active_from_min, th.active_to_min)).length;
  const windowsOpen = snapshot.missions.filter((m) => active(t, m.window_start_min, m.window_end_min)).length;
  const t0 = snapshot.scenario.t0;

  const LAYERS: { key: Layer; label: string; symbol: ReactNode; count: number }[] = [
    { key: "bases", label: "Air bases (fictional)", count: snapshot.bases.length, symbol: <rect x="3" y="3" width="10" height="10" rx="2" fill="var(--color-base)" stroke="white" strokeWidth="1.5" /> },
    { key: "missions", label: "Mission areas", count: snapshot.missions.length, symbol: <path d="M8 2 14 8 8 14 2 8Z" fill="var(--color-p2)" stroke="white" strokeWidth="1.2" /> },
    { key: "threats", label: "Threat zones", count: snapshot.threats.length, symbol: <circle cx="8" cy="8" r="6" fill="rgb(217 45 32 / 0.25)" stroke="var(--color-threat)" strokeWidth="1.5" /> },
    { key: "airspace", label: "Airspace restrictions", count: snapshot.airspace.length, symbol: <rect x="2.5" y="3.5" width="11" height="9" fill="rgb(71 84 103 / 0.1)" stroke="var(--color-airspace)" strokeWidth="1.3" strokeDasharray="2.5 1.5" /> },
    { key: "routes", label: "Planned sorties", count: assignments.length, symbol: <path d="M2 12 14 4" stroke="var(--color-route)" strokeWidth="2.2" strokeLinecap="round" /> },
    { key: "airfields", label: "Alternate airfields (open data)", count: snapshot.alternate_airfields.length, symbol: <circle cx="8" cy="8" r="3.5" fill="white" stroke="var(--color-ink-3)" strokeWidth="1.5" /> },
  ];

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card padded={false} className="flex min-w-0 flex-col overflow-hidden">
        {/* Time control */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line px-4 py-4 sm:px-5">
          <div className="flex w-full min-w-0 flex-1 items-center gap-4 sm:min-w-[340px]">
            <div className="shrink-0">
              <div className="text-xs font-medium text-ink-3">Scenario time</div>
              <div className="font-display text-lg font-semibold text-ink tnum">{tmin(t)}</div>
            </div>
            <div className="flex-1">
              <input type="range" min={0} max={horizon} step={15} value={t} onChange={(ev) => setT(Number(ev.target.value))} className="w-full" aria-label="Scenario time" />
              <div className="mt-0.5 flex justify-between text-[11px] text-ink-4 tnum">
                {[0, 0.25, 0.5, 0.75, 1].map((f) => <span key={f}>{tmin(horizon * f)}</span>)}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] text-ink-3 tnum">{istAt(t0, t)}</span>
            <Badge tone={threatsOn ? "red" : "grey"} dot size="md">{threatsOn} threat zone{threatsOn === 1 ? "" : "s"} active</Badge>
            <Badge tone={windowsOpen ? "violet" : "grey"} dot size="md">{windowsOpen} mission window{windowsOpen === 1 ? "" : "s"} open</Badge>
            <Badge tone={airborne.length ? "green" : "grey"} dot size="md">{airborne.length} sortie{airborne.length === 1 ? "" : "s"} airborne</Badge>
          </div>
        </div>

        {/* Map */}
        <div ref={box} className="relative h-[60vh] min-h-[360px] bg-map-sea lg:h-[calc(100vh-410px)] lg:min-h-[500px]">
          <svg
            ref={svg}
            viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
            className="absolute inset-0 block h-full w-full [&_[data-hit]]:cursor-pointer cursor-grab touch-none select-none active:cursor-grabbing"
            data-testid="cop-map"
            onWheel={onWheel}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
          >
            <defs>
              <pattern id="hatch" width={fs(6)} height={fs(6)} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2={fs(6)} stroke="var(--color-threat)" strokeOpacity="0.35" strokeWidth={fs(1.5)} />
              </pattern>
            </defs>
            <rect x={-WIDTH * 2} y={-H * 2} width={WIDTH * 5} height={H * 5} fill="var(--color-map-sea)" />
            {land.map((cn) => (
              <path
                key={cn.iso + cn.name}
                d={cn.d}
                fill={cn.iso === "IND" ? "var(--color-map-land)" : "var(--color-map-land-other)"}
                stroke={cn.iso === "IND" ? "var(--color-map-border)" : "#c4c9d1"}
                strokeWidth={cn.iso === "IND" ? 1.3 : 0.8}
                vectorEffect="non-scaling-stroke"
                fillRule="evenodd"
              />
            ))}
            {grid.filter((g) => g > e.minLon && g < e.maxLon).map((g) => (
              <g key={`lon${g}`}>
                <line x1={x(g)} x2={x(g)} y1={-H} y2={H * 2} stroke="#94a3b8" strokeOpacity={0.22} strokeWidth={1} vectorEffect="non-scaling-stroke" />
                <text x={x(g) + fs(4)} y={view.y + fs(16)} fontSize={fs(10.5)} fill="#8b95a5" className="tnum">{g}°E</text>
              </g>
            ))}
            {grid.filter((g) => g > e.minLat && g < e.maxLat).map((g) => (
              <g key={`lat${g}`}>
                <line y1={y(g)} y2={y(g)} x1={-WIDTH} x2={WIDTH * 2} stroke="#94a3b8" strokeOpacity={0.22} strokeWidth={1} vectorEffect="non-scaling-stroke" />
                <text x={view.x + fs(8)} y={y(g) - fs(4)} fontSize={fs(10.5)} fill="#8b95a5" className="tnum">{g}°N</text>
              </g>
            ))}
            {land.filter((cn) => LABELLED.has(cn.iso)).map((cn) => (
              <text
                key={`lbl${cn.iso}`}
                x={cn.lx}
                y={cn.ly}
                textAnchor="middle"
                fontSize={fs(cn.iso === "IND" ? 20 : 12)}
                fontWeight={cn.iso === "IND" ? 700 : 600}
                letterSpacing={fs(cn.iso === "IND" ? 8 : 2)}
                fill={cn.iso === "IND" ? "#d6d3d1" : "#b5bcc7"}
                className="pointer-events-none uppercase"
              >
                {cn.name}
              </text>
            ))}

            {shown.airspace && snapshot.airspace.map((zn) => {
              const on = active(t, zn.active_from_min, zn.active_to_min);
              return (
                <polygon
                  key={zn.id}
                  points={zn.polygon.coordinates[0].map(([lon, lat]) => `${x(lon)},${y(lat)}`).join(" ")}
                  fill={on ? "rgb(71 84 103 / 0.13)" : "rgb(71 84 103 / 0.03)"}
                  stroke="var(--color-airspace)"
                  strokeOpacity={on ? 0.7 : 0.3}
                  strokeDasharray="6 4"
                  strokeWidth={1.4}
                  vectorEffect="non-scaling-stroke"
                  {...bind({
                    key: zn.id,
                    kind: "Airspace restriction",
                    title: `${humanize(zn.kind)} airspace`,
                    subtitle: zn.id,
                    rows: [["Active", `${tmin(zn.active_from_min)} to ${tmin(zn.active_to_min)}`], ["At selected time", on ? "Active" : "Inactive"]],
                  })}
                />
              );
            })}

            {shown.threats && snapshot.threats.map((th) => {
              const on = active(t, th.active_from_min, th.active_to_min);
              const cx = x(th.center.lon);
              const cy = y(th.center.lat);
              const rr = Math.max(r(th.radius_km), fs(4));
              return (
                <g
                  key={th.id}
                  {...bind({
                    key: th.id,
                    kind: "Threat zone (synthetic)",
                    title: humanize(th.type),
                    subtitle: th.id,
                    rows: [
                      ["Radius", `${th.radius_km.toFixed(0)} km`],
                      ["Severity", `${th.severity.toFixed(2)} of 1`],
                      ["Active", `${tmin(th.active_from_min)} to ${tmin(th.active_to_min)}`],
                      ["At selected time", on ? "Active" : "Inactive"],
                    ],
                  })}
                >
                  <circle cx={cx} cy={cy} r={rr} fill={on ? `rgb(217 45 32 / ${0.08 + th.severity * 0.16})` : "rgb(217 45 32 / 0.02)"} />
                  {on && <circle cx={cx} cy={cy} r={rr} fill="url(#hatch)" />}
                  {on && <circle className="pulse-ring" cx={cx} cy={cy} r={rr} fill="none" stroke="var(--color-threat)" strokeWidth={2} vectorEffect="non-scaling-stroke" />}
                  <circle cx={cx} cy={cy} r={rr} fill="none" stroke="var(--color-threat)" strokeOpacity={on ? 0.95 : 0.3} strokeDasharray={on ? undefined : "4 4"} strokeWidth={on ? 1.6 : 1.2} vectorEffect="non-scaling-stroke" />
                </g>
              );
            })}

            {shown.routes && assignments.map((a, i) => {
              const b = baseById.get(a.base_from);
              const m = missionById.get(a.mission_id);
              if (!b || !m) return null;
              const pts = a.route?.length ? a.route : [{ lat: b.lat, lon: b.lon }, m.aoi.center];
              const flying = active(t, a.takeoff_min, a.land_min);
              return (
                <polyline
                  key={a.id}
                  className="enter-fade"
                  style={{ ["--d" as string]: 500 + i * 30 }}
                  points={pts.map((q) => `${x(q.lon)},${y(q.lat)}`).join(" ")}
                  fill="none"
                  stroke="var(--color-route)"
                  strokeOpacity={flying ? 1 : 0.35}
                  strokeWidth={flying ? 3 : 1.4}
                  strokeLinecap="round"
                  strokeDasharray={a.frozen || flying ? undefined : "1 0"}
                  vectorEffect="non-scaling-stroke"
                  {...bind({
                    key: a.id,
                    kind: "Planned sortie",
                    title: `${a.mission_id} · ${a.aircraft_id}`,
                    subtitle: a.id,
                    rows: [
                      ["From", a.base_from],
                      ["Take-off", tmin(a.takeoff_min)],
                      ["Landing", tmin(a.land_min)],
                      ["Crew", a.crew_ids.join(", ")],
                      ["Risk", <Badge key="r" tone={riskTone(a.risk.total)} dot>{a.risk.total.toFixed(2)}</Badge>],
                      ["At selected time", flying ? "Airborne" : a.takeoff_min > t ? "Not yet airborne" : "Landed"],
                    ],
                  })}
                />
              );
            })}

            {shown.missions && snapshot.missions.map((m, i) => {
              const on = active(t, m.window_start_min, m.window_end_min);
              const covered = assignments.filter((a) => a.mission_id === m.id);
              const cx = x(m.aoi.center.lon);
              const cy = y(m.aoi.center.lat);
              const s = fs(10 - m.priority);
              return (
                <g
                  key={m.id}
                  opacity={on ? 1 : 0.55}
                  {...bind({
                    key: m.id,
                    kind: "Mission area",
                    title: <span className="flex items-center gap-2"><PriorityChip p={m.priority} compact />{m.id}</span>,
                    subtitle: m.name,
                    rows: [
                      ["Type", CAPABILITIES[m.capability_required] ?? m.capability_required],
                      ["Window", `${tmin(m.window_start_min)} to ${tmin(m.window_end_min)}`],
                      ["Aircraft needed", String(m.aircraft_required)],
                      ["Area radius", `${m.aoi.radius_km.toFixed(0)} km`],
                      ["In plan", covered.length ? covered.map((a) => `${a.aircraft_id} at ${tmin(a.takeoff_min)}`).join(", ") : planLabel ? "Not covered" : "No plan yet"],
                    ],
                  })}
                >
                  <circle cx={cx} cy={cy} r={Math.max(r(m.aoi.radius_km), s)} fill={pColor(m.priority)} fillOpacity={0.07} stroke={pColor(m.priority)} strokeOpacity={0.45} strokeWidth={1} vectorEffect="non-scaling-stroke" />
                  <path
                    className="enter-pop"
                    style={{ ["--d" as string]: 250 + i * 12 }}
                    d={`M${cx} ${cy - s}L${cx + s} ${cy}L${cx} ${cy + s}L${cx - s} ${cy}Z`}
                    fill={covered.length ? pColor(m.priority) : "white"}
                    stroke={covered.length ? (m.priority >= 4 ? pColor(3) : "white") : pColor(Math.min(3, m.priority))}
                    strokeWidth={fs(covered.length ? 1.5 : 2)}
                  />
                </g>
              );
            })}

            {shown.airfields && snapshot.alternate_airfields.map((a) => (
              <circle
                key={a.id}
                cx={x(a.lon)}
                cy={y(a.lat)}
                r={fs(3.5)}
                fill="white"
                stroke="var(--color-ink-3)"
                strokeWidth={fs(1.5)}
                {...bind({ key: a.id, kind: "Alternate airfield (open data)", title: a.name, subtitle: a.id, rows: [["Source", `${a.provenance.source}, public civil airport`], ["Use", "Diversion option"]] })}
              />
            ))}

            {shown.bases && snapshot.bases.map((b, i) => (
              <g
                key={b.id}
                {...bind({
                  key: b.id,
                  kind: "Air base (fictional)",
                  title: b.name,
                  subtitle: b.id,
                  rows: [
                    ["Region", REGIONS[b.region] ?? b.region],
                    ["Elevation", `${Math.round(b.elevation_m * 3.28084).toLocaleString()} ft`],
                    ["Runways", String(b.runways)],
                    ["Aircraft based", String(snapshot.aircraft.filter((a) => a.base_id === b.id).length)],
                    ["Sorties planned", String(assignments.filter((a) => a.base_from === b.id).length)],
                  ],
                })}
              >
                <rect className="enter-pop" style={{ ["--d" as string]: 100 + i * 80 }} x={x(b.lon) - fs(7)} y={y(b.lat) - fs(7)} width={fs(14)} height={fs(14)} rx={fs(3)} fill="var(--color-base)" stroke="white" strokeWidth={fs(2)} />
                <text x={x(b.lon) + fs(12)} y={y(b.lat) + fs(4.5)} fontSize={fs(13)} fontWeight={600} fill="var(--color-ink)" stroke="white" strokeWidth={fs(3.5)} paintOrder="stroke" strokeLinejoin="round">
                  {b.name}
                </text>
              </g>
            ))}
          </svg>

          {/* Controls */}
          <div className="absolute right-3 top-3 flex flex-col gap-2 sm:right-4 sm:top-4">
            <IconButton icon="plus" label="Zoom in" onClick={() => zoomAt(0.7, c.cx, c.cy)} />
            <IconButton icon="minus" label="Zoom out" onClick={() => zoomAt(1 / 0.7, c.cx, c.cy)} />
            <IconButton icon="crosshair" label="Fit India" onClick={() => setCam(null)} />
            <IconButton icon="maximize" label="Show every plotted object" onClick={() => setCam(all)} />
          </div>
          <div className="pointer-events-none absolute bottom-3 left-3 flex max-w-[calc(100%-1.5rem)] items-center gap-2 sm:bottom-4 sm:left-4 lg:max-w-[70%] rounded-lg border border-line bg-surface/95 px-3 py-2 text-xs text-ink-3 shadow-card backdrop-blur">
            <Icon name="info" size={14} className="shrink-0" />
            <span>
              {geoError ? "Map outline could not be loaded; objects are drawn on the grid only. " : "Outline: Natural Earth (public domain), India point of view, simplified. "}
              <b className="font-semibold text-ink-2">Boundaries are not authoritative.</b>
            </span>
          </div>
          <div className="pointer-events-none absolute bottom-4 right-4 hidden rounded-lg bg-surface/90 px-2.5 py-1.5 text-[11px] text-ink-3 shadow-card xl:block">Scroll to zoom · drag to pan · click for details</div>

          {hover && (
            <div
              className="pointer-events-none absolute z-10 w-56 animate-pop-in sm:w-64 rounded-xl border border-line bg-surface/97 p-3.5 shadow-overlay backdrop-blur"
              style={{
                left: size && hover.x > size.w - 290 ? hover.x - 276 : hover.x + 16,
                top: size && hover.y > size.h - 220 ? Math.max(8, hover.y - 200) : hover.y + 16,
              }}
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-4">{hover.info.kind}</div>
              <div className="mt-0.5 text-sm font-semibold text-ink">{hover.info.title}</div>
              {hover.info.subtitle && <div className="truncate text-xs text-ink-3">{hover.info.subtitle}</div>}
              <div className="mt-2 border-t border-line pt-1 [&_dl>div]:py-1.5 [&_dl>div]:text-xs">
                <DetailRows rows={hover.info.rows.slice(0, 4)} />
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Side panel: layers + legend, selection */}
      <div className="flex flex-col gap-6">
        <Card className="!p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">Layers and legend</h2>
            <Tooltip content="Toggle a layer on or off. Bold or filled shapes are active at the selected time.">
              <span tabIndex={0} className="text-ink-4"><Icon name="info" size={15} /></span>
            </Tooltip>
          </div>
          <div className="mt-3 flex flex-col gap-0.5">
            {LAYERS.map((l) => (
              <label key={l.key} className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-subtle">
                <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={shown[l.key]} onChange={() => setShown({ ...shown, [l.key]: !shown[l.key] })} />
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>{l.symbol}</svg>
                <span className={`flex-1 text-[13px] ${shown[l.key] ? "text-ink-2" : "text-ink-4"}`}>{l.label}</span>
                <span className="text-xs text-ink-4 tnum">{l.count}</span>
              </label>
            ))}
          </div>
          <div className="mt-4 border-t border-line pt-4">
            <div className="text-xs font-medium text-ink-3">Mission priority (marker colour and size)</div>
            <div className="mt-2 flex items-center gap-2">
              {[1, 2, 3, 4, 5].map((p) => (
                <span key={p} className="flex flex-1 flex-col items-center gap-1">
                  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
                    <path d={`M9 ${9 - (9 - p) * 0.95}L${9 + (9 - p) * 0.95} 9L9 ${9 + (9 - p) * 0.95}L${9 - (9 - p) * 0.95} 9Z`} fill={pColor(p)} />
                  </svg>
                  <span className="text-[11px] text-ink-3">P{p}</span>
                </span>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-4 text-xs text-ink-3">
              <span className="flex items-center gap-1.5"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 1 11 6 6 11 1 6Z" fill="var(--color-p2)" /></svg>Covered by plan</span>
              <span className="flex items-center gap-1.5"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 1.5 10.5 6 6 10.5 1.5 6Z" fill="white" stroke="var(--color-p2)" strokeWidth="1.5" /></svg>Not covered</span>
            </div>
            <p className="mt-3 text-xs leading-5 text-ink-3">Circles show each zone&apos;s true radius in km. Dashed outlines are inactive at the selected time.</p>
          </div>
        </Card>

        <Card className="!p-5">
          <h2 className="text-sm font-semibold text-ink">Selected</h2>
          {selected ? (
            <div className="mt-3">
              <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-4">{selected.kind}</div>
              <div className="mt-0.5 text-[15px] font-semibold text-ink">{selected.title}</div>
              {selected.subtitle && <div className="text-[13px] text-ink-3">{selected.subtitle}</div>}
              <div className="mt-2"><DetailRows rows={selected.rows} /></div>
              <Button size="sm" variant="ghost" icon="x" className="mt-2 -ml-2" onClick={() => setSelected(null)}>Clear</Button>
            </div>
          ) : (
            <p className="mt-2 text-[13px] leading-5 text-ink-3">Hover over any shape for a quick look; click it to keep its details here.</p>
          )}
          <div className="mt-4 border-t border-line pt-3 text-xs text-ink-3">Routes shown: {planLabel ?? "no plan yet"}.</div>
        </Card>
      </div>
    </div>
  );
}
