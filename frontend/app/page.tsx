"use client";

import { useState } from "react";
import { api, setScenarioId, useApi, useScenarioId } from "@/lib/api";
import type { ScenarioSummary, Snapshot } from "@/lib/types";
import { Badge, Button, Card, ErrorBox, Loading, NeedScenario, PageHeader, Stat, Table, Td } from "@/components/ui";

const countBy = <T,>(xs: T[], pick: (x: T) => string) =>
  xs.reduce<Record<string, number>>((acc, x) => ({ ...acc, [pick(x)]: (acc[pick(x)] ?? 0) + 1 }), {});

export default function ScenarioPage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const list = useApi<{ scenarios: ScenarioSummary[] }>("/scenarios");
  const [seed, setSeed] = useState(42);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(label: string, path: string, body: unknown) {
    setBusy(label);
    setError(null);
    try {
      const s = await api<ScenarioSummary>(path, { method: "POST", body });
      setScenarioId(s.scenario_id);
      list.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const s = snap.data;
  const aircraftStatus = s ? countBy(s.aircraft, (a) => a.status) : {};
  const crewStatus = s ? countBy(s.crew, (c) => c.status) : {};

  return (
    <>
      <PageHeader
        title="Scenario"
        subtitle="Load the saved demo scenario or generate a new seeded synthetic one. The same seed always produces the same scenario."
        actions={
          <>
            <Button variant="primary" disabled={busy !== null} onClick={() => run("load", "/scenarios/load", { path: "demo.json" })}>
              {busy === "load" ? "Loading…" : "Load demo scenario"}
            </Button>
            <label className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-2 text-sm">
              Seed
              <input
                type="number"
                min={0}
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                className="w-20 py-1 tabular-nums outline-none"
              />
            </label>
            <Button disabled={busy !== null} onClick={() => run("gen", "/scenarios/generate", { seed })}>
              {busy === "gen" ? "Generating…" : "Generate"}
            </Button>
          </>
        }
      />
      {error && <ErrorBox message={error} />}

      {!scenarioId ? (
        <NeedScenario />
      ) : snap.error ? (
        <ErrorBox message={snap.error} onRetry={snap.reload} />
      ) : !s ? (
        <Loading what="scenario snapshot" />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span className="font-semibold text-slate-900">{s.scenario.name}</span>
            <Badge>{s.scenario_id}</Badge>
            <Badge>seed {s.scenario.seed}</Badge>
            <Badge>horizon {s.scenario.horizon_min} min</Badge>
            <Badge tone="blue">{s.scenario.season_preset}</Badge>
            <Badge tone="amber" title="Data label reported by the API">data: {s.data_label}</Badge>
            <Badge title="Fused state version (pins + events)">state v{s.state_version}</Badge>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Stat label="Bases" value={s.bases.length} />
            <Stat label="Aircraft" value={s.aircraft.length} hint={`${aircraftStatus.SERVICEABLE ?? 0} serviceable`} />
            <Stat label="Crew" value={s.crew.length} hint={`${crewStatus.AVAILABLE ?? 0} available`} />
            <Stat label="Missions" value={s.missions.length} />
            <Stat label="Threat zones" value={s.threats.length} />
            <Stat label="Airspace zones" value={s.airspace.length} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Bases">
              <Table head={["Base", "Region", "Elevation", "Runways", "Lat / lon"]}>
                {s.bases.map((b) => (
                  <tr key={b.id}>
                    <Td className="font-medium">{b.name}</Td>
                    <Td>{b.region}</Td>
                    <Td className="tabular-nums">{Math.round(b.elevation_m * 3.28084).toLocaleString()} ft</Td>
                    <Td className="tabular-nums">{b.runways}</Td>
                    <Td className="tabular-nums">{b.lat.toFixed(2)}, {b.lon.toFixed(2)}</Td>
                  </tr>
                ))}
              </Table>
            </Card>
            <Card title="Aircraft status">
              <div className="flex flex-wrap gap-2">
                {Object.entries(aircraftStatus).map(([k, v]) => (
                  <Badge key={k} tone={k === "SERVICEABLE" ? "green" : k === "UNSERVICEABLE" ? "red" : "amber"}>
                    {k}: {v}
                  </Badge>
                ))}
              </div>
              <h3 className="mb-2 mt-4 text-sm font-semibold text-slate-800">Crew status</h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(crewStatus).map(([k, v]) => (
                  <Badge key={k} tone={k === "AVAILABLE" ? "green" : "amber"}>{k}: {v}</Badge>
                ))}
              </div>
              <p className="mt-4 text-xs text-slate-500">
                Bases, units and tail numbers are fictional. Aircraft types are generic placeholders with illustrative numbers.
              </p>
            </Card>
          </div>
        </>
      )}

      <Card title="Scenarios on the server">
        {list.error ? (
          <ErrorBox message={list.error} onRetry={list.reload} />
        ) : !list.data ? (
          <Loading what="scenarios" />
        ) : list.data.scenarios.length === 0 ? (
          <p className="text-sm text-slate-600">None yet.</p>
        ) : (
          <Table head={["Name", "Id", "Seed", "Season", ""]}>
            {list.data.scenarios.map((x) => (
              <tr key={x.scenario_id} className={x.scenario_id === scenarioId ? "bg-sky-50" : ""}>
                <Td className="font-medium">{x.name}</Td>
                <Td className="font-mono text-xs">{x.scenario_id}</Td>
                <Td className="tabular-nums">{x.seed}</Td>
                <Td>{x.season_preset}</Td>
                <Td>
                  {x.scenario_id === scenarioId ? (
                    <Badge tone="blue">current</Badge>
                  ) : (
                    <Button onClick={() => setScenarioId(x.scenario_id)}>Use</Button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
