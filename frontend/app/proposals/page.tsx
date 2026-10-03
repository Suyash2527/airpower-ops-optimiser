"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getScenarioId } from "@/lib/api";

interface Proposal {
  id: string;
  rank: number;
  fallback: boolean;
  status: string;
  explanation: string;
  score_breakdown: Record<string, number>;
}

// Advisory only: the operator identifies themselves and each decision is an explicit click.
const ACTOR = "planner-ui";

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<string | null>(null);  // proposal id with a decision in flight

  const refresh = useCallback(async () => {
    const id = getScenarioId();
    if (!id) return setError("Load a scenario first (Scenario page).");
    try {
      setProposals(await api<Proposal[]>(`/proposals?scenario_id=${id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  async function guarded(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const inject = () =>
    guarded(async () => {
      const scenario_id = getScenarioId();
      if (!scenario_id) throw new Error("Load a scenario and generate a plan first.");
      const r = await api<{ events: { type: string; time_min: number }[]; note?: string | null }>(
        "/events/simulate",
        { method: "POST", body: { scenario_id, seed: 1, count: 1, propose: true } },
      );
      const e = r.events[0];
      setNote(`Injected simulated event: ${e?.type} at t+${e?.time_min} min. ${r.note ?? ""}`);
    });

  // Only the proposal being decided is locked, so a second proposal can still be clicked.
  const decide = async (id: string, verb: "approve" | "reject") => {
    setPending(id);
    setError(null);
    try {
      await api(`/proposals/${id}/${verb}`, { method: "POST", body: { actor: ACTOR } });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <button disabled={busy} onClick={inject} className="rounded border px-3 py-1">
          Inject one simulated event
        </button>
        <span className="ml-3 text-sm">Requires a generated plan. Nothing is approved automatically.</span>
      </div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {note && <p className="text-sm">{note}</p>}
      {proposals.length === 0 && <p className="text-sm">No proposals.</p>}
      <ul className="flex flex-col gap-2">
        {proposals.map((p) => (
          <li key={p.id} className="rounded border p-3 text-sm">
            <p className="font-semibold">
              #{p.rank} {p.fallback ? "(fallback) " : ""}— {p.status}
            </p>
            <p>{p.explanation}</p>
            <p>
              Score: {Object.entries(p.score_breakdown).map(([k, v]) => `${k} ${v}`).join(" · ") || "not measured"}
            </p>
            {p.status === "open" && (
              <div className="mt-2 flex gap-2">
                <button disabled={pending === p.id} className="rounded border px-3 py-1" onClick={() => decide(p.id, "approve")}>Approve</button>
                <button disabled={pending === p.id} className="rounded border px-3 py-1" onClick={() => decide(p.id, "reject")}>Reject</button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
