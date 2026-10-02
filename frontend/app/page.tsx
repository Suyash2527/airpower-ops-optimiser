"use client";

import { useEffect, useState } from "react";
import MapView from "@/components/MapView";
import { api, getScenarioId, setScenarioId, type ScenarioSummary } from "@/lib/api";

export default function ScenarioPage() {
  const [current, setCurrent] = useState<ScenarioSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const id = getScenarioId();
    if (!id) return;
    api<{ scenarios: ScenarioSummary[] }>("/scenarios")
      .then((r) => setCurrent(r.scenarios.find((s) => s.scenario_id === id) ?? null))
      .catch((e: Error) => setError(e.message));
  }, []);

  async function run(path: string, body: unknown) {
    setBusy(true);
    setError(null);
    try {
      const s = await api<ScenarioSummary>(path, { method: "POST", body });
      setScenarioId(s.scenario_id);
      setCurrent(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex flex-1 flex-col gap-3 p-4">
      <div className="flex gap-2">
        <button disabled={busy} className="rounded border px-3 py-1"
          onClick={() => run("/scenarios/load", { path: "demo.json" })}>
          Load saved demo scenario
        </button>
        <button disabled={busy} className="rounded border px-3 py-1"
          onClick={() => run("/scenarios/generate", { seed: 42 })}>
          Generate (seed 42)
        </button>
      </div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {current ? (
        <dl className="text-sm">
          <dt className="font-semibold">{current.name}</dt>
          <dd>id {current.scenario_id} · seed {current.seed} · horizon {current.horizon_min} min · {current.season_preset} · label: {current.data_label}</dd>
          <dd>{Object.entries(current.counts).map(([k, v]) => `${k}: ${v}`).join(" · ")}</dd>
        </dl>
      ) : (
        <p className="text-sm">No scenario loaded.</p>
      )}
      <MapView />
    </main>
  );
}
