"use client";

import { useState } from "react";
import { api, useApi, useScenarioId } from "@/lib/api";
import type { Plan, Proposal } from "@/lib/types";
import { Badge, Button, Card, Empty, ErrorBox, Loading, NeedScenario, PageHeader, Table, Td, statusTone, tmin } from "@/components/ui";

// Advisory only: the operator identifies themselves and each decision is an explicit click.
const ACTOR = "planner-ui";

const show = (field: string, v: unknown) =>
  Array.isArray(v) ? v.join(", ") : typeof v === "number" && field.endsWith("_min") ? tmin(v) : String(v);
const signed = (v: number, digits = 2) => `${v > 0 ? "+" : ""}${v.toFixed(digits)}`;

export default function ProposalsPage() {
  const scenarioId = useScenarioId();
  const proposals = useApi<Proposal[]>(scenarioId ? `/proposals?scenario_id=${scenarioId}` : null);
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const [seed, setSeed] = useState(1);
  const [injecting, setInjecting] = useState(false);
  const [pending, setPending] = useState<string | null>(null); // proposal with a decision in flight
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const active = plans.data ? [...plans.data].reverse().find((p) => p.status === "approved") ?? null : null;
  const all = proposals.data ?? [];
  const open = all.filter((p) => p.status === "open").sort((a, b) => a.rank - b.rank);
  const history = all.filter((p) => p.status !== "open").reverse();

  async function inject() {
    setInjecting(true);
    setError(null);
    setNote(null);
    try {
      const r = await api<{ events: { type: string; time_min: number; description?: string }[]; note?: string | null }>(
        "/events/simulate",
        { method: "POST", body: { scenario_id: scenarioId, seed, count: 1, propose: true } },
      );
      const e = r.events[0];
      setNote(`Injected ${e?.type ?? "event"} at ${e ? tmin(e.time_min) : "?"}${e?.description ? `: ${e.description}` : ""}. ${r.note ?? ""}`);
      setSeed((s) => s + 1);
      proposals.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setInjecting(false);
    }
  }

  async function decide(id: string, verb: "approve" | "reject") {
    setPending(id);
    setError(null);
    try {
      await api(`/proposals/${id}/${verb}`, { method: "POST", body: { actor: ACTOR } });
      setNote(verb === "approve" ? `Proposal ${id} approved: it is now the active plan. Sibling proposals expired.` : `Proposal ${id} rejected.`);
      proposals.reload();
      plans.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Retasking proposals"
        subtitle="Inject a simulated disruption. The system ranks repair options against the active plan; nothing changes until a person approves one."
        actions={
          scenarioId && (
            <>
              <label className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-2 text-sm">
                Event seed
                <input type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="w-16 py-1 tabular-nums outline-none" />
              </label>
              <Button variant="primary" disabled={injecting || !active} onClick={inject} title={active ? undefined : "Approve a plan first"}>
                {injecting ? "Injecting and solving (up to 20 s)…" : "Inject simulated event"}
              </Button>
            </>
          )
        }
      />
      {error && <ErrorBox message={error} />}
      {note && <div role="status" className="rounded-md border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900">{note}</div>}

      {!scenarioId ? (
        <NeedScenario />
      ) : proposals.error || plans.error ? (
        <ErrorBox message={(proposals.error ?? plans.error)!} onRetry={() => { proposals.reload(); plans.reload(); }} />
      ) : !proposals.data || !plans.data ? (
        <Loading what="proposals" />
      ) : (
        <>
          <p className="text-sm text-slate-600">
            Active plan:{" "}
            {active ? <><b>{active.id}</b> <Badge>v{active.version}</Badge></> : <span className="text-amber-700">none. Approve a plan on the Plan page before injecting events.</span>}
          </p>

          {open.length === 0 ? (
            <Empty>No open proposals. Inject a simulated event to get ranked options.</Empty>
          ) : (
            <div className="flex flex-col gap-4">
              {open.map((p) => (
                <ProposalCard key={p.id} p={p}>
                  <div className="flex gap-2">
                    <Button variant="primary" disabled={pending === p.id} onClick={() => decide(p.id, "approve")}>
                      {pending === p.id ? "Working…" : "Approve"}
                    </Button>
                    <Button variant="danger" disabled={pending === p.id} onClick={() => decide(p.id, "reject")}>Reject</Button>
                  </div>
                </ProposalCard>
              ))}
            </div>
          )}

          <Card
            title={
              <button className="flex w-full items-center justify-between" onClick={() => setShowHistory(!showHistory)}>
                <span>Decided and expired proposals ({history.length})</span>
                <span className="text-xs font-normal text-sky-700">{showHistory ? "Hide" : "Show"}</span>
              </button>
            }
          >
            {!showHistory ? (
              <p className="text-sm text-slate-600">Hidden. Newest first when shown.</p>
            ) : history.length === 0 ? (
              <p className="text-sm text-slate-600">None yet.</p>
            ) : (
              <Table head={["Proposal", "Event", "Option", "Status", "Changes", "Score (total)"]}>
                {history.map((p) => (
                  <tr key={p.id}>
                    <Td className="font-mono text-xs">{p.id}</Td>
                    <Td>{p.event_description}</Td>
                    <Td>#{p.rank} {p.preset}{p.fallback ? " (fallback)" : ""}</Td>
                    <Td><Badge tone={statusTone(p.status)}>{p.status}</Badge></Td>
                    <Td className="tabular-nums">{p.diff.n_changes}</Td>
                    <Td className="tabular-nums">{p.score_breakdown.total?.toFixed(2) ?? "not measured"}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}

function ProposalCard({ p, children }: { p: Proposal; children: React.ReactNode }) {
  const d = p.diff;
  return (
    <Card
      title={
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-base">Option #{p.rank}</span>
          <Badge tone="blue">{p.preset}</Badge>
          {p.fallback && <Badge tone="amber" title="Every optimiser variant ran out of time; this is the greedy repair">fallback</Badge>}
          <span className="font-normal text-slate-600">· {p.event_description}</span>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm text-slate-700">{p.explanation}</p>
        <div className="flex flex-wrap gap-2 text-sm">
          <Badge tone={d.coverage_delta >= 0 ? "green" : "red"}>coverage {signed(d.coverage_delta)}</Badge>
          <Badge tone={d.risk_delta <= 0 ? "green" : "red"}>risk {signed(d.risk_delta, 3)}</Badge>
          <Badge>{d.n_changes} change(s)</Badge>
          {Object.entries(p.score_breakdown).map(([k, v]) => (
            <Badge key={k} title="Score component (weights are placeholders, D-60)">score {k} {v.toFixed(2)}</Badge>
          ))}
        </div>
        {d.added.length + d.removed.length + d.changed.length === 0 ? (
          <p className="text-sm text-slate-600">No sortie changes.</p>
        ) : (
          <Table head={["Sortie", "Change", "Field", "Before", "After"]}>
            {d.removed.map((id) => (
              <tr key={`r${id}`} className="bg-red-50/50">
                <Td className="font-mono text-xs">{id}</Td><Td><Badge tone="red">removed</Badge></Td><Td>—</Td><Td>—</Td><Td>—</Td>
              </tr>
            ))}
            {d.added.map((id) => (
              <tr key={`a${id}`} className="bg-emerald-50/50">
                <Td className="font-mono text-xs">{id}</Td><Td><Badge tone="green">added</Badge></Td><Td>—</Td><Td>—</Td><Td>—</Td>
              </tr>
            ))}
            {d.changed.map((c, i) => (
              <tr key={`c${i}`}>
                <Td className="font-mono text-xs">{c.assignment_id}</Td>
                <Td><Badge tone="amber">changed</Badge></Td>
                <Td>{c.field}</Td>
                <Td className="text-slate-500 line-through">{show(c.field, c.from)}</Td>
                <Td className="font-medium">{show(c.field, c.to)}</Td>
              </tr>
            ))}
          </Table>
        )}
        {children}
      </div>
    </Card>
  );
}
