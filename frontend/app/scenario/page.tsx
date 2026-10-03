"use client";

import { useState } from "react";
import { api, setScenarioId, useApi, useScenarioId } from "@/lib/api";
import type { ScenarioSummary, Snapshot } from "@/lib/types";
import { REGIONS, SEASONS } from "@/lib/labels";
import { healthTone, humanize, plural } from "@/lib/format";
import { Badge, Button, Card, CardHeader, Icon, KpiCard, Meter, NumberField, PageHeader, PageSkeleton, PriorityChip, Select, StatusDot, Table, Td, Tr, ErrorState, Skeleton } from "@/components/ui";
import { Gate, useAction } from "@/components/shell/states";

// Saved, seeded scenario files under scenarios/ (see scenarios/README.md).
const SAVED = [
  { file: "demo.json", label: "Demo · monsoon, seed 42" },
  { file: "monsoon_flood_hadr.json", label: "Monsoon flood relief · seed 101" },
  { file: "winter_fog_north.json", label: "Winter fog, north · seed 202" },
  { file: "cyclone_east_coast.json", label: "Cyclone, east coast · seed 303" },
  { file: "pre_monsoon_heat_dust.json", label: "Pre-monsoon heat and dust · seed 404" },
];

const countBy = <T,>(xs: T[], pick: (x: T) => string) =>
  xs.reduce<Record<string, number>>((acc, x) => ({ ...acc, [pick(x)]: (acc[pick(x)] ?? 0) + 1 }), {});

export default function ScenarioPage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const list = useApi<{ scenarios: ScenarioSummary[] }>("/scenarios");
  const [file, setFile] = useState(SAVED[0].file);
  const [seed, setSeed] = useState(42);
  const { busy, run } = useAction();

  const start = (label: string, path: string, body: unknown) =>
    run(
      label,
      () => api<ScenarioSummary>(path, { method: "POST", body }),
      (s) => {
        setScenarioId(s.scenario_id);
        list.reload();
        return [`Scenario ready: ${s.name}`, `${plural(s.counts.aircraft ?? 0, "aircraft", "aircraft")}, ${plural(s.counts.missions ?? 0, "mission")}. All data is synthetic.`];
      },
      "Could not load the scenario",
    );

  return (
    <>
      <PageHeader
        title="Scenario"
        purpose="Choose the synthetic situation to plan against. The same seed always produces the same scenario, so every result can be reproduced."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader icon="book" title="Load a saved scenario" subtitle="Curated, seeded scenarios covering India's main seasons and regions." />
          <div className="mt-5 flex flex-wrap items-end gap-3">
            <Select label="Scenario file" value={file} onChange={(e) => setFile(e.target.value)} className="w-80">
              {SAVED.map((s) => <option key={s.file} value={s.file}>{s.label}</option>)}
            </Select>
            <Button variant="primary" icon="database" loading={busy === "load"} disabled={busy !== null} onClick={() => start("load", "/scenarios/load", { path: file })}>
              Load scenario
            </Button>
          </div>
        </Card>
        <Card>
          <CardHeader icon="sparkle" title="Generate from a seed" subtitle="Builds a new synthetic scenario with the default monsoon preset." />
          <div className="mt-5 flex flex-wrap items-end gap-3">
            <NumberField label="Seed" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
            <Button icon="sparkle" loading={busy === "gen"} disabled={busy !== null} onClick={() => start("gen", "/scenarios/generate", { seed })}>
              Generate scenario
            </Button>
          </div>
        </Card>
      </div>

      <Gate
        scenarioId={scenarioId}
        error={snap.error}
        ready={!!snap.data}
        onRetry={snap.reload}
        skeleton={<PageSkeleton kpis={4} rows={4} />}
      >
        {() => <Summary s={snap.data!} />}
      </Gate>

      <Card padded={false}>
        <div className="p-6 pb-4">
          <CardHeader title="Scenarios on the server" subtitle="Every scenario loaded or generated in this deployment. Switch to any of them." />
        </div>
        {list.error ? (
          <div className="px-6 pb-6"><ErrorState message={list.error} onRetry={list.reload} /></div>
        ) : !list.data ? (
          <div className="flex flex-col gap-3 px-6 pb-6">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : (
          <div className="border-t border-line [&>div]:rounded-none [&>div]:border-0 [&>div]:shadow-none">
            <Table head={["Name", "Season", "Seed", "Aircraft", "Missions", "Scenario id", ""]}>
              {list.data.scenarios.map((x) => {
                const current = x.scenario_id === scenarioId;
                return (
                  <Tr key={x.scenario_id} selected={current}>
                    <Td className="font-medium capitalize text-ink">{x.name}</Td>
                    <Td>{SEASONS[x.season_preset] ?? x.season_preset}</Td>
                    <Td className="tnum">{x.seed}</Td>
                    <Td className="tnum">{x.counts.aircraft}</Td>
                    <Td className="tnum">{x.counts.missions}</Td>
                    <Td className="font-mono text-xs text-ink-3">{x.scenario_id}</Td>
                    <Td className="text-right">
                      {current ? (
                        <Badge tone="blue" icon="check">Current</Badge>
                      ) : (
                        <Button size="sm" onClick={() => setScenarioId(x.scenario_id)}>Use this</Button>
                      )}
                    </Td>
                  </Tr>
                );
              })}
            </Table>
          </div>
        )}
      </Card>
    </>
  );
}

function Summary({ s }: { s: Snapshot }) {
  const ac = countBy(s.aircraft, (a) => a.status);
  const cr = countBy(s.crew, (c) => c.status);
  const pri = countBy(s.missions, (m) => String(m.priority));
  const regions = s.scenario.region_mix ?? {};

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="font-display text-xl font-semibold capitalize text-ink">{s.scenario.name}</h2>
        <Badge tone="blue" size="md">{SEASONS[s.scenario.season_preset] ?? s.scenario.season_preset}</Badge>
        <Badge size="md">Seed {s.scenario.seed}</Badge>
        <Badge size="md">{s.scenario.horizon_min / 60} h horizon</Badge>
        {Object.keys(regions).map((r) => <Badge key={r} size="md">{REGIONS[r] ?? r}</Badge>)}
        <Badge tone="amber" size="md" icon="alert">Data: {s.data_label}</Badge>
      </div>

      <div className="grid grid-cols-4 gap-6">
        <KpiCard icon="home" label="Bases" value={s.bases.length} meaning="Fictional air bases at real locations and elevations." />
        <KpiCard
          icon="plane"
          tone="green"
          label="Aircraft serviceable"
          value={ac.SERVICEABLE ?? 0}
          unit={`of ${s.aircraft.length}`}
          meaning="Ready to fly now; the rest are degraded, in maintenance or down."
          footer={<Meter value={(ac.SERVICEABLE ?? 0) / Math.max(1, s.aircraft.length)} color="var(--color-emerald-500)" />}
        />
        <KpiCard
          icon="users"
          tone="green"
          label="Crew available"
          value={cr.AVAILABLE ?? 0}
          unit={`of ${s.crew.length}`}
          meaning="Can be rostered; others are resting, on duty or sick."
          footer={<Meter value={(cr.AVAILABLE ?? 0) / Math.max(1, s.crew.length)} color="var(--color-emerald-500)" />}
        />
        <KpiCard
          icon="target"
          tone="violet"
          label="Missions requested"
          value={s.missions.length}
          meaning={`${s.threats.length} threat zones and ${s.airspace.length} airspace restrictions constrain them.`}
          footer={
            <div className="flex h-2 overflow-hidden rounded-full">
              {[1, 2, 3, 4, 5].map((p) => (
                <span key={p} title={`P${p}: ${pri[p] ?? 0}`} style={{ flex: pri[p] ?? 0, background: `var(--color-p${p})` }} />
              ))}
            </div>
          }
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card padded={false}>
          <div className="p-6 pb-4"><CardHeader icon="home" title="Bases" subtitle="Names are fictional codenames; positions and elevations are real places." /></div>
          <div className="border-t border-line [&>div]:rounded-none [&>div]:border-0 [&>div]:shadow-none">
            <Table head={["Base", "Region", "Elevation", "Runways", "Aircraft", "Position"]}>
              {s.bases.map((b) => (
                <Tr key={b.id}>
                  <Td><div className="font-medium text-ink">{b.name}</div>{b.name !== b.id && <div className="font-mono text-xs text-ink-3">{b.id}</div>}</Td>
                  <Td>{REGIONS[b.region] ?? b.region}</Td>
                  <Td className="tnum">{Math.round(b.elevation_m * 3.28084).toLocaleString()} ft</Td>
                  <Td className="tnum">{b.runways}</Td>
                  <Td className="tnum">{s.aircraft.filter((a) => a.base_id === b.id).length}</Td>
                  <Td className="whitespace-nowrap tnum text-ink-3">{b.lat.toFixed(2)}°N {b.lon.toFixed(2)}°E</Td>
                </Tr>
              ))}
            </Table>
          </div>
        </Card>
        <Card>
          <CardHeader icon="gauge" title="Readiness" subtitle="Status of every aircraft and crew member at scenario start." />
          <StatusBreakdown title="Aircraft" counts={ac} total={s.aircraft.length} />
          <StatusBreakdown title="Crew" counts={cr} total={s.crew.length} />
          <div className="mt-5 border-t border-line pt-4">
            <div className="text-[13px] font-medium text-ink-2">Missions by priority</div>
            <div className="mt-3 flex flex-wrap gap-3">
              {[1, 2, 3, 4, 5].map((p) => (
                <span key={p} className="flex items-center gap-1.5 text-sm text-ink-2 tnum"><PriorityChip p={p} compact /> {pri[p] ?? 0}</span>
              ))}
            </div>
          </div>
        </Card>
      </div>
      <p className="flex items-center gap-2 text-[13px] text-ink-3">
        <Icon name="info" size={15} />
        Units, tail numbers and aircraft types are fictional placeholders with illustrative performance numbers.
      </p>
    </section>
  );
}

function StatusBreakdown({ title, counts, total }: { title: string; counts: Record<string, number>; total: number }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="font-medium text-ink-2">{title}</span>
        <span className="text-ink-3 tnum">{total} total</span>
      </div>
      <div className="mt-2 flex h-2 gap-0.5 overflow-hidden rounded-full">
        {entries.map(([k, v]) => {
          const t = healthTone(k);
          return <span key={k} style={{ flex: v }} className={t === "green" ? "bg-emerald-500" : t === "red" ? "bg-red-500" : "bg-amber-400"} />;
        })}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
        {entries.map(([k, v]) => <StatusDot key={k} tone={healthTone(k)} label={<span>{humanize(k)} <b className="font-semibold text-ink tnum">{v}</b></span>} />)}
      </div>
    </div>
  );
}
