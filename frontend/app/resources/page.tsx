"use client";

import { useState } from "react";
import { useApi, useScenarioId } from "@/lib/api";
import type { FusionMeta, FusionReport, Snapshot } from "@/lib/types";
import { Badge, Card, Empty, ErrorBox, Loading, NeedScenario, PageHeader, Stat, Table, Td, tmin } from "@/components/ui";

type Tab = "aircraft" | "crew" | "missions" | "conflicts";
const TABS: [Tab, string][] = [["aircraft", "Fleet"], ["crew", "Crew"], ["missions", "Missions"], ["conflicts", "Data conflicts"]];

const fmt = (v: unknown) => (typeof v === "object" ? JSON.stringify(v) : String(v));

/** How fresh and how agreed-upon a fused record is. */
function Freshness({ meta }: { meta?: FusionMeta }) {
  if (!meta) return <Badge>no fusion data</Badge>;
  return (
    <div className="flex flex-wrap gap-1">
      {meta.stale ? (
        <Badge tone="red" title={`Stale fields: ${Object.keys(meta.stale_fields).join(", ") || "record"}`}>stale · {Math.round(meta.staleness_min)} min</Badge>
      ) : (
        <Badge tone="green" title={`Last observed ${Math.round(meta.staleness_min)} min before fusion time`}>fresh · {Math.round(meta.staleness_min)} min</Badge>
      )}
      {meta.sources.length > 1 && <Badge tone="blue" title={meta.sources.join(", ")}>{meta.sources.length} sources</Badge>}
      {meta.conflict_fields.length > 0 && (
        <Badge tone="amber" title={`Sources disagree on: ${meta.conflict_fields.join(", ")}`}>conflict: {meta.conflict_fields.join(", ")}</Badge>
      )}
      {meta.pinned_fields.length > 0 && <Badge tone="blue">pinned: {meta.pinned_fields.join(", ")}</Badge>}
    </div>
  );
}

const statusTone = (s: string) =>
  ["SERVICEABLE", "AVAILABLE"].includes(s) ? "green" : ["UNSERVICEABLE", "SICK"].includes(s) ? "red" : "amber";

export default function ResourcesPage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const report = useApi<FusionReport>(scenarioId ? `/scenarios/${scenarioId}/fusion-report` : null);
  const [tab, setTab] = useState<Tab>("aircraft");
  const [group, setGroup] = useState("all");
  const err = snap.error ?? report.error;

  return (
    <>
      <PageHeader
        title="Fleet, crew and missions"
        subtitle="The fused view of each record: which source it came from, how old it is, and where the two synthetic sources disagree."
      />
      {!scenarioId ? (
        <NeedScenario />
      ) : err ? (
        <ErrorBox message={err} onRetry={() => { snap.reload(); report.reload(); }} />
      ) : !snap.data || !report.data ? (
        <Loading what="fused records" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Records fused" value={report.data.counts.records} hint={`${report.data.counts.multi_source} from two sources`} />
            <Stat label="Fields compared" value={report.data.counts.fields_compared} hint={`${report.data.counts.fields_agree} agree`} />
            <Stat label="Open conflicts" value={report.data.counts.conflicts_open} hint={`${report.data.counts.conflicts_pinned} pinned by a person`} />
            <Stat label="Stale records" value={report.data.counts.stale_records} hint={`${report.data.counts.discarded_stale_observations} stale observations discarded`} />
          </div>

          <div className="flex flex-wrap gap-1 border-b border-slate-200" role="tablist">
            {TABS.map(([k, label]) => (
              <button
                key={k}
                role="tab"
                aria-selected={tab === k}
                onClick={() => setTab(k)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === k ? "border-sky-700 text-sky-800" : "border-transparent text-slate-600 hover:text-slate-900"}`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "aircraft" && (
            <Table head={["Aircraft", "Tail", "Type", "Base", "Status", "Available from", "Hours since maint.", "Fuel", "Freshness"]}>
              {snap.data.aircraft.map((a) => (
                <tr key={a.id} className="hover:bg-slate-50">
                  <Td className="font-medium">{a.id}</Td>
                  <Td className="font-mono text-xs">{a.tail}</Td>
                  <Td>{a.type_id}</Td>
                  <Td>{a.base_id}</Td>
                  <Td><Badge tone={statusTone(a.status)}>{a.status}</Badge></Td>
                  <Td className="tabular-nums">{tmin(a.available_from_min)}</Td>
                  <Td className="tabular-nums">{a.hours_since_maintenance.toFixed(1)} h</Td>
                  <Td className="tabular-nums">{a.fuel_state_pct.toFixed(0)}%</Td>
                  <Td><Freshness meta={snap.data!.fusion_meta.aircraft?.[a.id]} /></Td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "crew" && (
            <Table head={["Crew", "Name", "Role", "Qualified on", "Base", "Status", "Duty last 24 h", "Freshness"]}>
              {snap.data.crew.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <Td className="font-medium">{c.id}</Td>
                  <Td className="font-mono text-xs">{c.name}</Td>
                  <Td>{c.role}</Td>
                  <Td>{c.qualifications.join(", ")}</Td>
                  <Td>{c.base_id}</Td>
                  <Td><Badge tone={statusTone(c.status)}>{c.status}</Badge></Td>
                  <Td className="tabular-nums">{c.duty_minutes_last_24h} min</Td>
                  <Td><Freshness meta={snap.data!.fusion_meta.crew?.[c.id]} /></Td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "missions" && (
            <Table head={["Mission", "Name", "Capability", "Priority", "Window", "Duration", "Aircraft", "Status", "Freshness"]}>
              {[...snap.data.missions].sort((a, b) => a.priority - b.priority || a.window_start_min - b.window_start_min).map((m) => (
                <tr key={m.id} className="hover:bg-slate-50">
                  <Td className="font-medium">{m.id}</Td>
                  <Td>{m.name}</Td>
                  <Td>{m.capability_required}</Td>
                  <Td><Badge tone={m.priority === 1 ? "red" : m.priority === 2 ? "amber" : "grey"}>P{m.priority}</Badge></Td>
                  <Td className="whitespace-nowrap tabular-nums">{tmin(m.window_start_min)} → {tmin(m.window_end_min)}</Td>
                  <Td className="tabular-nums">{m.duration_min} min</Td>
                  <Td className="tabular-nums">{m.aircraft_required}</Td>
                  <Td><Badge>{m.status}</Badge></Td>
                  <Td><Freshness meta={snap.data!.fusion_meta.missions?.[m.id]} /></Td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "conflicts" && (
            <Card
              title={
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>Where the sources disagree ({report.data.conflicts.length})</span>
                  <select className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm font-normal" value={group} onChange={(e) => setGroup(e.target.value)}>
                    <option value="all">All groups</option>
                    {[...new Set(report.data.conflicts.map((c) => c.group))].map((g) => <option key={g} value={g}>{g}</option>)}
                  </select>
                </div>
              }
            >
              {report.data.conflicts.length === 0 ? (
                <Empty>No conflicts: every multi-source field agrees.</Empty>
              ) : (
                <Table head={["Record", "Field", "Kept value", "Other reports", "Rule", "Status"]}>
                  {report.data.conflicts.filter((c) => group === "all" || c.group === group).map((c) => (
                    <tr key={c.id} className="hover:bg-slate-50" title={c.explanation}>
                      <Td><span className="text-xs text-slate-500">{c.group}</span><br /><span className="font-medium">{c.entity_id}</span></Td>
                      <Td>{c.field}</Td>
                      <Td>
                        <span className="font-medium">{fmt(c.resolved_value)}</span>
                        <br /><span className="text-xs text-slate-500">from {c.resolved_source}</span>
                      </Td>
                      <Td className="text-xs">
                        {c.candidates.filter((x) => !x.selected).map((x) => (
                          <div key={x.source + x.age_min}>
                            {fmt(x.value)} <span className="text-slate-500">({x.source}, {Math.round(x.age_min)} min old, score {x.score.toFixed(2)}{x.stale ? ", stale" : ""})</span>
                          </div>
                        ))}
                      </Td>
                      <Td><Badge>{c.reason}</Badge></Td>
                      <Td><Badge tone={c.status === "pinned" ? "blue" : "amber"}>{c.status}</Badge></Td>
                    </tr>
                  ))}
                </Table>
              )}
              <p className="mt-3 text-xs text-slate-500">{report.data.config.notice}</p>
            </Card>
          )}
        </>
      )}
    </>
  );
}
