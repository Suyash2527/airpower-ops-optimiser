"use client";

import { useState } from "react";
import { useApi, useScenarioId } from "@/lib/api";
import type { Conflict, FusionMeta, FusionReport, Snapshot } from "@/lib/types";
import { CAPABILITIES } from "@/lib/labels";
import { dur, healthTone, humanize, tmin } from "@/lib/format";
import {
  Badge, Button, EmptyState, Icon, KpiCard, PageHeader, PageSkeleton, PriorityChip, Segmented, StatusDot, Table, Tabs, Td, Tooltip, Tr,
} from "@/components/ui";
import { Gate } from "@/components/shell/states";

type Tab = "aircraft" | "crew" | "missions" | "conflicts";
const PAGE = 12;

const fmt = (v: unknown) =>
  typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)) : typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
const SOURCE_NAMES: Record<string, string> = { SYNTHETIC: "Primary feed", SYNTHETIC_SECONDARY: "Secondary feed" };
const sourceName = (s: string) => SOURCE_NAMES[s] ?? humanize(s);

/** How fresh and how agreed-upon a fused record is. */
function Freshness({ meta }: { meta?: FusionMeta }) {
  if (!meta) return <span className="text-xs text-ink-4">no fusion data</span>;
  const age = Math.round(meta.staleness_min);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Tooltip
        content={
          meta.stale
            ? `Stale: newest winning report is ${age} min old, beyond this record type's maximum age. Stale fields: ${Object.keys(meta.stale_fields).join(", ") || "record"}.`
            : `Fresh: newest winning report is ${age} min old, within the maximum age for this record type.`
        }
      >
        <span tabIndex={0}><Badge tone={meta.stale ? "red" : "green"} dot>{meta.stale ? "Stale" : "Fresh"} · {age} min</Badge></span>
      </Tooltip>
      {meta.sources.length > 1 && (
        <Tooltip content={`Reported by ${meta.sources.map(sourceName).join(" and ")}.`}>
          <span tabIndex={0}><Badge tone="grey" icon="layers">{meta.sources.length} sources</Badge></span>
        </Tooltip>
      )}
      {meta.conflict_fields.length > 0 && (
        <Tooltip content={`The sources disagree on: ${meta.conflict_fields.join(", ")}. See the Conflicts tab for which value was kept and why.`}>
          <span tabIndex={0}><Badge tone="amber" icon="alert">{meta.conflict_fields.length} conflict{meta.conflict_fields.length > 1 ? "s" : ""}</Badge></span>
        </Tooltip>
      )}
      {meta.pinned_fields.length > 0 && <Badge tone="blue" icon="lock">pinned</Badge>}
    </div>
  );
}

export default function ResourcesPage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const report = useApi<FusionReport>(scenarioId ? `/scenarios/${scenarioId}/fusion-report` : null);
  const [tab, setTab] = useState<Tab>("aircraft");
  const err = snap.error ?? report.error;

  return (
    <>
      <PageHeader
        title="Fleet & crew"
        purpose="One fused record per aircraft, crew member and mission: where it came from, how old it is, and where the two data feeds disagree."
      />
      <Gate
        scenarioId={scenarioId}
        error={err}
        ready={!!snap.data && !!report.data}
        onRetry={() => { snap.reload(); report.reload(); }}
        skeleton={<PageSkeleton kpis={4} rows={10} />}
      >
        {() => {
          const s = snap.data!;
          const r = report.data!;
          const c = r.counts;
          return (
            <>
              <div className="stagger grid grid-cols-4 gap-6">
                <KpiCard icon="layers" tone="blue" label="Records fused" value={c.records} meaning={`${c.multi_source} of them were reported by both feeds and merged.`} />
                <KpiCard icon="check" tone="green" label="Fields in agreement" value={c.fields_agree} unit={`of ${c.fields_compared}`} meaning="Fields reported by both feeds with the same value." />
                <KpiCard icon="alert" tone="amber" label="Open conflicts" value={c.conflicts_open} meaning={`Feeds disagree; a rule picked one value. ${c.conflicts_pinned} pinned by a person.`} />
                <KpiCard icon="clock" tone="red" label="Stale records" value={c.stale_records} meaning={`Older than their maximum age. ${c.discarded_stale_observations} stale reports were set aside.`} />
              </div>

              <div className="flex flex-col gap-4">
                <Tabs
                  value={tab}
                  onChange={setTab}
                  tabs={[
                    { key: "aircraft", label: "Fleet", count: s.aircraft.length, icon: "plane" },
                    { key: "crew", label: "Crew", count: s.crew.length, icon: "users" },
                    { key: "missions", label: "Missions", count: s.missions.length, icon: "target" },
                    { key: "conflicts", label: "Data conflicts", count: r.conflicts.length, icon: "layers" },
                  ]}
                />

                {tab === "aircraft" && (
                  <Table head={["Aircraft", "Type", "Base", "Status", "Available from", "Since maintenance", "Fuel", "Data freshness"]}>
                    {s.aircraft.map((a) => (
                      <Tr key={a.id}>
                        <Td><div className="font-medium text-ink">{a.id}</div><div className="font-mono text-xs text-ink-3">{a.tail}</div></Td>
                        <Td>{a.type_id}</Td>
                        <Td className="whitespace-nowrap">{a.base_id}</Td>
                        <Td><StatusDot tone={healthTone(a.status)} label={humanize(a.status)} /></Td>
                        <Td className="tnum">{a.available_from_min > 0 ? tmin(a.available_from_min) : <span className="text-ink-4">now</span>}</Td>
                        <Td className="tnum">{a.hours_since_maintenance.toFixed(1)} h</Td>
                        <Td className="w-32">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-14 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${a.fuel_state_pct}%` }} /></div>
                            <span className="text-xs tnum">{a.fuel_state_pct.toFixed(0)}%</span>
                          </div>
                        </Td>
                        <Td><Freshness meta={s.fusion_meta.aircraft?.[a.id]} /></Td>
                      </Tr>
                    ))}
                  </Table>
                )}

                {tab === "crew" && (
                  <Table head={["Crew", "Role", "Qualified on", "Base", "Status", "Duty in last 24 h", "Data freshness"]}>
                    {s.crew.map((c2) => (
                      <Tr key={c2.id}>
                        <Td><div className="font-medium text-ink">{c2.id}</div><div className="font-mono text-xs text-ink-3">{c2.name}</div></Td>
                        <Td>{humanize(c2.role)}</Td>
                        <Td><div className="flex flex-wrap gap-1">{c2.qualifications.map((q) => <Badge key={q}>{q}</Badge>)}</div></Td>
                        <Td>{c2.base_id}</Td>
                        <Td><StatusDot tone={healthTone(c2.status)} label={humanize(c2.status)} /></Td>
                        <Td className="w-44">
                          <Tooltip content={`${c2.duty_minutes_last_24h} of the 720-minute limit in a rolling 24 hours (placeholder rule).`}>
                            <div className="flex w-full items-center gap-2" tabIndex={0}>
                              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                                <div className={`h-full rounded-full ${c2.duty_minutes_last_24h > 540 ? "bg-amber-500" : "bg-brand-500"}`} style={{ width: `${Math.min(100, (c2.duty_minutes_last_24h / 720) * 100)}%` }} />
                              </div>
                              <span className="text-xs tnum">{dur(c2.duty_minutes_last_24h)}</span>
                            </div>
                          </Tooltip>
                        </Td>
                        <Td><Freshness meta={s.fusion_meta.crew?.[c2.id]} /></Td>
                      </Tr>
                    ))}
                  </Table>
                )}

                {tab === "missions" && (
                  <Table head={["Mission", "Type", "Window", "On station", "Aircraft", "Status", "Data freshness"]}>
                    {[...s.missions].sort((a, b) => a.priority - b.priority || a.window_start_min - b.window_start_min).map((m) => (
                      <Tr key={m.id}>
                        <Td>
                          <div className="flex items-center gap-2.5">
                            <PriorityChip p={m.priority} compact />
                            <div><div className="font-medium text-ink">{m.id}</div><div className="max-w-64 truncate text-xs text-ink-3">{m.name}</div></div>
                          </div>
                        </Td>
                        <Td>{CAPABILITIES[m.capability_required] ?? m.capability_required}</Td>
                        <Td className="whitespace-nowrap tnum">{tmin(m.window_start_min)} <span className="text-ink-4">→</span> {tmin(m.window_end_min)}</Td>
                        <Td className="tnum">{dur(m.duration_min)}</Td>
                        <Td className="tnum">{m.aircraft_required}</Td>
                        <Td><Badge>{humanize(m.status)}</Badge></Td>
                        <Td><Freshness meta={s.fusion_meta.missions?.[m.id]} /></Td>
                      </Tr>
                    ))}
                  </Table>
                )}

                {tab === "conflicts" && <Conflicts report={r} />}
              </div>
            </>
          );
        }}
      </Gate>
    </>
  );
}

function Conflicts({ report }: { report: FusionReport }) {
  const groups = [...new Set(report.conflicts.map((c) => c.group))];
  const [group, setGroup] = useState("all");
  const [shown, setShown] = useState(PAGE);
  const rows = report.conflicts.filter((c) => group === "all" || c.group === group);

  if (report.conflicts.length === 0) return <EmptyState icon="checkCircle" title="No conflicts">Every field reported by both feeds agrees.</EmptyState>;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          value={group}
          onChange={(g) => { setGroup(g); setShown(PAGE); }}
          options={[{ key: "all", label: `All (${report.conflicts.length})` }, ...groups.map((g) => ({ key: g, label: `${humanize(g)} (${report.conflicts.filter((c) => c.group === g).length})` }))]}
        />
        <p className="flex items-center gap-2 text-[13px] text-ink-3">
          <span className="h-3 w-3 rounded border-2 border-brand-500 bg-brand-50" /> Value kept by the fusion rule
        </p>
      </div>
      <div className="stagger grid grid-cols-2 gap-4">
        {rows.slice(0, shown).map((c) => <ConflictCard key={c.id} c={c} />)}
      </div>
      {shown < rows.length && (
        <div className="flex justify-center">
          <Button icon="chevronDown" onClick={() => setShown(shown + PAGE)}>Show {Math.min(PAGE, rows.length - shown)} more of {rows.length - shown}</Button>
        </div>
      )}
      <p className="flex items-start gap-2 text-[13px] text-ink-3"><Icon name="info" size={15} className="mt-0.5" />{report.config.notice}</p>
    </div>
  );
}

function ConflictCard({ c }: { c: Conflict }) {
  const cands = [...c.candidates].sort((a, b) => Number(b.selected) - Number(a.selected));
  return (
    <div className="lift rounded-card border border-line bg-surface p-5 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium text-ink-3">{humanize(c.group)}</div>
          <div className="mt-0.5 text-[15px] font-semibold text-ink">
            {c.entity_id} <span className="font-normal text-ink-4">·</span> <span className="font-mono text-[13px] font-medium text-ink-2">{c.field}</span>
          </div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <Tooltip content={c.explanation}><span tabIndex={0}><Badge tone="grey" icon="sliders">{humanize(c.reason)}</Badge></span></Tooltip>
          <Badge tone={c.status === "pinned" ? "blue" : "amber"} dot>{c.status === "pinned" ? "Pinned" : "Open"}</Badge>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3">
        {cands.map((x, i) => (
          <div key={x.source + i} className={`relative rounded-lg border p-3.5 ${x.selected ? "border-brand-500 bg-brand-50/50 ring-1 ring-brand-500" : "border-line bg-subtle"}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-ink-2">{sourceName(x.source)}</span>
              {x.selected ? <Badge tone="blue" icon="check">Kept</Badge> : <Badge tone="grey">Set aside</Badge>}
            </div>
            <div className={`mt-2 truncate font-display text-lg font-semibold tnum ${x.selected ? "text-ink" : "text-ink-3"}`} title={fmt(x.value)}>{fmt(x.value)}</div>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-3 tnum">
              <span>{Math.round(x.age_min)} min old</span>
              <Tooltip content="Fusion score = source trust x confidence x freshness decay. Higher wins (placeholder weights, D-38).">
                <span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-2">score {x.score.toFixed(2)}</span>
              </Tooltip>
              {x.stale && <span className="font-medium text-red-600">stale</span>}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[13px] leading-5 text-ink-3">{c.explanation}</p>
    </div>
  );
}
