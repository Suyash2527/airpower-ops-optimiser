"use client";

import { useState } from "react";
import { api, useApi, useScenarioId } from "@/lib/api";
import type { Assignment, Plan, Proposal, Snapshot } from "@/lib/types";
import { FIELD_LABELS, preset } from "@/lib/labels";
import { plural, signed, statusTone, tmin } from "@/lib/format";
import {
  Badge, Button, Callout, Card, CardHeader, EmptyState, Icon, Modal, NumberField, PageHeader, PriorityChip, Skeleton, StatusDot, Table, Td, Tooltip, Tr,
  SkeletonCards,
} from "@/components/ui";
import { Gate, useAction } from "@/components/shell/states";

// Advisory only: the operator identifies themselves and each decision is an explicit click.
const ACTOR = "planner-ui";

const show = (field: string, v: unknown) =>
  Array.isArray(v) ? v.join(", ") : typeof v === "number" && field.endsWith("_min") ? tmin(v) : String(v);

export default function ProposalsPage() {
  const scenarioId = useScenarioId();
  const proposals = useApi<Proposal[]>(scenarioId ? `/proposals?scenario_id=${scenarioId}` : null);
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const [seed, setSeed] = useState(1);
  const [confirm, setConfirm] = useState<Proposal | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const { busy, run } = useAction();

  const active = plans.data ? [...plans.data].reverse().find((p) => p.status === "approved") ?? null : null;
  const all = proposals.data ?? [];
  const open = all.filter((p) => p.status === "open").sort((a, b) => a.rank - b.rank);
  const history = all.filter((p) => p.status !== "open").reverse();

  const inject = () =>
    run(
      "inject",
      () =>
        api<{ events: { type: string; time_min: number; description?: string }[]; note?: string | null }>("/events/simulate", {
          method: "POST",
          body: { scenario_id: scenarioId, seed, count: 1, propose: true },
        }),
      (r) => {
        const e = r.events[0];
        setSeed((s) => s + 1);
        proposals.reload();
        snap.reload();
        return [`Disruption injected at ${e ? tmin(e.time_min) : "?"}`, `${e?.description ?? e?.type ?? "Event"}. ${r.note ?? "Ranked options are below. Nothing has changed yet."}`];
      },
      "Could not inject the event",
    );

  const decide = (p: Proposal, verb: "approve" | "reject") =>
    run(
      `${verb}:${p.id}`,
      () => api(`/proposals/${p.id}/${verb}`, { method: "POST", body: { actor: ACTOR } }),
      () => {
        setConfirm(null);
        proposals.reload();
        plans.reload();
        return verb === "approve"
          ? [`Option #${p.rank} approved`, "It is now the active plan. The other options expired. Recorded in the audit log."]
          : [`Option #${p.rank} rejected`, "The active plan is unchanged. Recorded in the audit log."];
      },
      verb === "approve" ? "Approval failed" : "Rejection failed",
    );

  return (
    <>
      <PageHeader
        title="Retasking"
        purpose="When something changes, AirPower checks the active plan and ranks ways to repair it. You compare the options and decide."
        actions={
          scenarioId && (
            <>
              <NumberField label="Event seed" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
              <div className="flex flex-col gap-1.5">
                <span className="select-none text-xs font-medium text-transparent" aria-hidden>Run</span>
                <Tooltip content={active ? "Injects one random synthetic disruption (seeded) and asks for re-plan options." : "Approve a plan on the Plan page first."}>
                  <Button variant="primary" icon="zap" loading={busy === "inject"} disabled={busy !== null || !active} onClick={inject}>
                    {busy === "inject" ? "Re-planning, up to 20 s" : "Simulate a disruption"}
                  </Button>
                </Tooltip>
              </div>
            </>
          )
        }
      />

      <Callout tone="amber" icon="shield" title="Nothing changes until a person approves.">
        These are proposals. The active plan stays in force until you approve one; approving it expires the others.
      </Callout>

      <Gate
        scenarioId={scenarioId}
        error={proposals.error ?? plans.error}
        ready={!!proposals.data && !!plans.data}
        onRetry={() => { proposals.reload(); plans.reload(); }}
        skeleton={<OptionSkeleton />}
      >
        {() => (
          <>
            <ActivePlanStrip active={active} />
            {busy === "inject" ? (
              <OptionSkeleton />
            ) : open.length === 0 ? (
              <EmptyState
                icon="shuffle"
                title="No open proposals"
                action={active && <Button variant="primary" icon="zap" onClick={inject}>Simulate a disruption</Button>}
              >
                {active
                  ? "Simulate a disruption (an aircraft fault, crew sickness, weather, a new threat or a priority change) to get ranked re-plan options."
                  : "Approve a plan on the Plan page first. Re-plans are always made against the active plan."}
              </EmptyState>
            ) : (
              <section className="stagger flex flex-col gap-5">
                <div className="flex items-start gap-3 rounded-card border border-line bg-surface p-5 shadow-card">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-50 text-red-600"><Icon name="zap" size={20} /></span>
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-[0.06em] text-ink-3">Disruption</div>
                    <div className="mt-0.5 text-base font-semibold text-ink first-letter:uppercase">{open[0].event_description}</div>
                    <div className="mt-0.5 text-[13px] text-ink-3">
                      {plural(open[0].affected_assignment_ids.length, "sortie")} of the active plan affected · {plural(open.length, "option")} ranked by score
                    </div>
                  </div>
                </div>
                {open.map((p) => (
                  <OptionCard
                    key={p.id}
                    p={p}
                    base={plans.data!.find((x) => x.id === p.base_plan_id) ?? null}
                    snap={snap.data}
                    busy={busy}
                    onApprove={() => setConfirm(p)}
                    onReject={() => decide(p, "reject")}
                  />
                ))}
              </section>
            )}

            <Card padded={false}>
              <button className="flex w-full items-center justify-between gap-4 p-4 text-left sm:p-6" onClick={() => setHistoryOpen(!historyOpen)} aria-expanded={historyOpen}>
                <CardHeader icon="history" title={`Decided and expired options (${history.length})`} subtitle="Every earlier option and what happened to it, newest first." />
                <Icon name="chevronDown" size={18} className={`text-ink-3 transition-transform ${historyOpen ? "rotate-180" : ""}`} />
              </button>
              <div className="collapsible" data-open={historyOpen}>
                <div>
                  {history.length === 0 ? (
                    <p className="px-6 pb-6 text-sm text-ink-3">None yet.</p>
                  ) : (
                    <div className="border-t border-line [&>div]:rounded-none [&>div]:border-0 [&>div]:shadow-none">
                      <Table head={["Disruption", "Option", "Outcome", "Changes", "Coverage", "Risk", "Score"]}>
                        {history.map((p) => (
                          <Tr key={p.id}>
                            <Td className="max-w-md"><div className="truncate first-letter:uppercase" title={p.event_description}>{p.event_description}</div></Td>
                            <Td className="whitespace-nowrap">#{p.rank} {preset(p.preset).label}{p.fallback ? " (fallback)" : ""}</Td>
                            <Td><Badge tone={statusTone(p.status)} dot>{p.status}</Badge></Td>
                            <Td className="tnum">{p.diff.n_changes}</Td>
                            <Td className="tnum">{signed(p.diff.coverage_delta * 100, 1)} pts</Td>
                            <Td className="tnum">{signed(p.diff.risk_delta, 3)}</Td>
                            <Td className="tnum">{p.score_breakdown.total?.toFixed(2) ?? "not measured"}</Td>
                          </Tr>
                        ))}
                      </Table>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          </>
        )}
      </Gate>

      {confirm && (
        <Modal
          open
          onClose={() => setConfirm(null)}
          icon="shield"
          tone="green"
          title={`Approve option #${confirm.rank}, ${preset(confirm.preset).label.toLowerCase()}?`}
          actions={
            <>
              <Button onClick={() => setConfirm(null)}>Cancel</Button>
              <Button variant="success" icon="check" loading={busy === `approve:${confirm.id}`} onClick={() => decide(confirm, "approve")}>
                Approve and make active
              </Button>
            </>
          }
        >
          This option becomes the active plan ({plural(confirm.diff.n_changes, "sortie change")}). The other open options expire. The
          decision is recorded in the audit log as <b className="text-ink">{ACTOR}</b>.
        </Modal>
      )}
    </>
  );
}

function ActivePlanStrip({ active }: { active: Plan | null }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-2">
      <span className="font-medium text-ink-3">Active plan</span>
      {active ? (
        <>
          <StatusDot tone="green" label={<span className="font-semibold text-ink">Version {active.version}</span>} />
          <span className="text-ink-3 tnum">
            {active.assignments.length} sorties · {active.kpis.missions_covered ?? "—"} of {active.kpis.missions_total ?? "—"} missions covered
          </span>
        </>
      ) : (
        <StatusDot tone="amber" label="None approved yet. Approve a plan on the Plan page before simulating a disruption." />
      )}
    </div>
  );
}

function OptionCard({
  p,
  base,
  snap,
  busy,
  onApprove,
  onReject,
}: {
  p: Proposal;
  base: Plan | null;
  snap: Snapshot | null;
  busy: string | null;
  onApprove: () => void;
  onReject: () => void;
}) {
  const [why, setWhy] = useState(false);
  const d = p.diff;
  const pr = preset(p.preset);
  const before = new Map((base?.assignments ?? []).map((a) => [a.id, a]));
  const after = new Map((p.plan?.assignments ?? []).map((a) => [a.id, a]));
  const priority = new Map((snap?.missions ?? []).map((m) => [m.id, m.priority]));
  const changed = new Map<string, typeof d.changed>();
  for (const c of d.changed) changed.set(c.assignment_id, [...(changed.get(c.assignment_id) ?? []), c]);
  const locked = busy !== null;

  return (
    <Card padded={false} className={p.rank === 1 ? "ring-1 ring-brand-200" : ""}>
      <div className="flex flex-wrap items-start justify-between gap-4 p-4 pb-4 sm:p-6 sm:pb-5">
        <div className="flex items-start gap-4">
          <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-base font-bold tnum ${p.rank === 1 ? "bg-brand-600 text-white" : "bg-slate-100 text-ink-2"}`}>#{p.rank}</span>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[17px] font-semibold text-ink">{pr.label}</h3>
              {p.rank === 1 && <Badge tone="blue">Highest score</Badge>}
              {p.fallback && (
                <Tooltip content="Every optimiser variant ran out of time, so this is the greedy repair (D-60).">
                  <span tabIndex={0}><Badge tone="amber" icon="alert">Fallback</Badge></span>
                </Tooltip>
              )}
            </div>
            <p className="mt-0.5 text-sm text-ink-3">{pr.sentence}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="danger" icon="x" loading={busy === `reject:${p.id}`} disabled={locked} onClick={onReject}>Reject</Button>
          <Button variant="success" icon="check" disabled={locked} onClick={onApprove}>Approve</Button>
        </div>
      </div>

      <div className="grid grid-cols-2 border-y border-line bg-subtle md:grid-cols-4">
        <Metric label="Coverage change" value={`${signed(d.coverage_delta * 100, 1)}`} unit="pts" good={d.coverage_delta > 0} bad={d.coverage_delta < 0} hint="Change in priority-weighted coverage versus the active plan, in percentage points." />
        <Metric label="Mean risk change" value={signed(d.risk_delta, 3)} good={d.risk_delta < 0} bad={d.risk_delta > 0} hint="Change in mean sortie risk (0 to 1). Lower is better." />
        <Metric label="Sorties changed" value={String(d.n_changes)} hint="Sorties added, removed or modified. Fewer changes are easier to brief." />
        <Metric
          label="Score"
          value={p.score_breakdown.total?.toFixed(2) ?? "not measured"}
          hint={`Score = 100 x coverage change − 20 x risk change − 1 per change (placeholder weights, D-60). Components: ${Object.entries(p.score_breakdown).filter(([k]) => k !== "total").map(([k, v]) => `${k} ${v.toFixed(2)}`).join(", ")}.`}
        />
      </div>

      <div className="p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-ink"><Icon name="diff" size={16} className="text-ink-3" /> Changes to the active plan</h4>
          <div className="flex items-center gap-3 text-xs text-ink-3">
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" />Added</span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-red-500" />Removed</span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-amber-500" />Changed</span>
          </div>
        </div>
        {d.added.length + d.removed.length + d.changed.length === 0 ? (
          <p className="mt-3 text-sm text-ink-3">No sortie changes: the active plan already copes with this event.</p>
        ) : (
          <div className="stagger mt-3 flex flex-col gap-2">
            {d.removed.map((id) => <DiffRow key={`r${id}`} kind="removed" id={id} a={before.get(id)} priority={priority} />)}
            {d.added.map((id) => <DiffRow key={`a${id}`} kind="added" id={id} a={after.get(id)} priority={priority} />)}
            {[...changed.entries()].map(([id, cs]) => (
              <DiffRow key={`c${id}`} kind="changed" id={id} a={after.get(id) ?? before.get(id)} priority={priority}>
                <div className="mt-2 flex flex-col gap-1.5">
                  {cs.map((c, i) => (
                    <div key={i} className="grid grid-cols-[88px_1fr] items-baseline gap-3 text-[13px] sm:grid-cols-[120px_1fr]">
                      <span className="text-ink-3">{FIELD_LABELS[c.field] ?? c.field}</span>
                      <span className="flex flex-wrap items-baseline gap-2 tnum">
                        <span className="rounded bg-red-50 px-1.5 text-red-700 line-through decoration-red-400">{show(c.field, c.from)}</span>
                        <Icon name="arrowRight" size={13} className="self-center text-ink-4" />
                        <span className="rounded bg-emerald-50 px-1.5 font-medium text-emerald-800">{show(c.field, c.to)}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </DiffRow>
            ))}
          </div>
        )}

        <button onClick={() => setWhy(!why)} className="mt-5 inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-700 hover:text-brand-800" aria-expanded={why}>
          <Icon name="chevronDown" size={15} className={`transition-transform ${why ? "rotate-180" : ""}`} />
          {why ? "Hide the full explanation" : "Read the full explanation"}
        </button>
        <div className="collapsible" data-open={why}>
          <div>
            <p className="mt-3 rounded-lg bg-subtle p-4 text-sm leading-6 text-ink-2">{p.explanation}</p>
          </div>
        </div>
      </div>
    </Card>
  );
}

function Metric({ label, value, unit, hint, good = false, bad = false }: { label: string; value: string; unit?: string; hint: string; good?: boolean; bad?: boolean }) {
  return (
    <Tooltip content={hint} className="block border-b border-r border-line px-4 py-3 sm:px-6 sm:py-4 md:border-b-0 md:last:border-r-0">
      <div tabIndex={0} className="w-full cursor-help">
        <div className="text-xs font-medium text-ink-3">{label}</div>
        <div className={`mt-1 font-display text-xl font-semibold tnum ${good ? "text-emerald-700" : bad ? "text-red-700" : "text-ink"}`}>
          {value}
          {unit && <span className="ml-1 text-sm font-medium text-ink-3">{unit}</span>}
        </div>
      </div>
    </Tooltip>
  );
}

const KIND = {
  added: { bar: "bg-emerald-500", box: "border-emerald-200 bg-emerald-50/40", tag: "text-emerald-700", icon: "plus" as const, word: "Added" },
  removed: { bar: "bg-red-500", box: "border-red-200 bg-red-50/40", tag: "text-red-700", icon: "minus" as const, word: "Removed" },
  changed: { bar: "bg-amber-500", box: "border-amber-200 bg-amber-50/30", tag: "text-amber-700", icon: "refresh" as const, word: "Changed" },
};

function DiffRow({ kind, id, a, priority, children }: { kind: keyof typeof KIND; id: string; a?: Assignment; priority: Map<string, number>; children?: React.ReactNode }) {
  const k = KIND[kind];
  const p = a ? priority.get(a.mission_id) : undefined;
  return (
    <div className={`relative overflow-hidden rounded-lg border py-3 pl-5 pr-4 ${k.box}`}>
      <span className={`absolute inset-y-0 left-0 w-1 ${k.bar}`} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className={`inline-flex w-[84px] items-center gap-1 text-xs font-semibold uppercase tracking-[0.04em] ${k.tag}`}>
          <Icon name={k.icon} size={13} strokeWidth={2.25} />
          {k.word}
        </span>
        {p !== undefined && <PriorityChip p={p} compact />}
        <span className={`font-medium ${kind === "removed" ? "text-ink-3 line-through decoration-red-400" : "text-ink"}`}>{a?.mission_id ?? id}</span>
        {a && (
          <span className="text-[13px] text-ink-3 tnum">
            {a.aircraft_id} · {a.base_from} · {tmin(a.takeoff_min)} → {tmin(a.land_min)}
          </span>
        )}
        <span className="ml-auto font-mono text-xs text-ink-4">{id}</span>
      </div>
      {children}
    </div>
  );
}

function OptionSkeleton() {
  return (
    <div className="flex flex-col gap-5" role="status" aria-label="Loading">
      <div className="flex items-center gap-3 rounded-card border border-line bg-surface p-5 shadow-card">
        <Skeleton className="h-10 w-10" />
        <div className="flex flex-1 flex-col gap-2"><Skeleton className="h-3 w-24" /><Skeleton className="h-4 w-96" /></div>
      </div>
      {[0, 1].map((i) => (
        <div key={i} className="rounded-card border border-line bg-surface p-6 shadow-card">
          <div className="flex items-center gap-4"><Skeleton className="h-11 w-11" /><div className="flex flex-col gap-2"><Skeleton className="h-4 w-40" /><Skeleton className="h-3 w-72" /></div></div>
          <div className="mt-5"><SkeletonCards n={4} /></div>
        </div>
      ))}
    </div>
  );
}
