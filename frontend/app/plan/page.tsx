"use client";

import { useState } from "react";
import { api, getScenarioId } from "@/lib/api";

interface Assignment {
  id: string;
  mission_id: string;
  aircraft_id: string;
  base_from: string;
  takeoff_min: number;
  land_min: number;
  reasons: { code?: string }[] | string[];
  explanation: string;
}
interface PlanResp {
  id: string;
  version: number;
  status: string;
  data_label: string;
  assignments: Assignment[];
  unassigned: { mission_id: string }[];
  solver: Record<string, unknown>;
}

export default function PlanPage() {
  const [plan, setPlan] = useState<PlanResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate() {
    const scenario_id = getScenarioId();
    if (!scenario_id) return setError("Load a scenario first (Scenario page).");
    setBusy(true);
    setError(null);
    try {
      setPlan(await api<PlanResp>("/plans/generate", { method: "POST", body: { scenario_id } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      setPlan(await api<PlanResp>(`/plans/${plan.id}/approve`, { method: "POST", body: { actor: "planner-ui" } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex flex-col gap-3 p-4">
      <div>
        <button disabled={busy} onClick={generate} className="rounded border px-3 py-1">
          {busy ? "Solving…" : "Generate plan"}
        </button>
        <span className="ml-3 text-sm">Advisory only: this plan is a proposal, not an order.</span>
      </div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {plan && (
        <>
          <p className="text-sm">
            Plan {plan.id} v{plan.version} · status {plan.status} · {plan.assignments.length} assigned ·{" "}
            {plan.unassigned.length} unassigned · label: {plan.data_label}
          </p>
          {plan.status === "draft" && (
            <div>
              <button disabled={busy} onClick={approve} className="rounded border px-3 py-1">Approve plan (human decision)</button>
            </div>
          )}
          <table className="text-left text-sm">
            <thead>
              <tr><th className="pr-3">Mission</th><th className="pr-3">Aircraft</th><th className="pr-3">Base</th><th className="pr-3">Take-off / land (min)</th><th>Why</th></tr>
            </thead>
            <tbody>
              {plan.assignments.map((a) => (
                <tr key={a.id} className="border-t align-top">
                  <td className="pr-3">{a.mission_id}</td>
                  <td className="pr-3">{a.aircraft_id}</td>
                  <td className="pr-3">{a.base_from}</td>
                  <td className="pr-3">{a.takeoff_min} / {a.land_min}</td>
                  <td>{a.explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
