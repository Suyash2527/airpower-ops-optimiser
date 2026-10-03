"use client";

import { useState } from "react";
import { useApi, useScenarioId } from "@/lib/api";
import type { AuditEntry } from "@/lib/types";
import { type Tone } from "@/lib/format";
import { Badge, Button, EmptyState, Icon, PageHeader, Select, SkeletonTable, Table, Td, Tooltip, Tr, useToast, type IconName } from "@/components/ui";
import { Gate } from "@/components/shell/states";

const ACTION: Record<string, { label: string; tone: Tone; icon: IconName }> = {
  "plan.generate": { label: "Plan generated", tone: "blue", icon: "zap" },
  "plan.approve": { label: "Plan approved", tone: "green", icon: "check" },
  "plan.supersede": { label: "Plan superseded", tone: "grey", icon: "history" },
  "event.inject": { label: "Event injected", tone: "amber", icon: "alert" },
  "retask.propose": { label: "Options proposed", tone: "violet", icon: "shuffle" },
  "proposal.approve": { label: "Option approved", tone: "green", icon: "check" },
  "proposal.reject": { label: "Option rejected", tone: "red", icon: "x" },
  "proposal.expire": { label: "Options expired", tone: "grey", icon: "clock" },
  "fusion.pin": { label: "Value pinned", tone: "blue", icon: "lock" },
};
const action = (a: string) =>
  ACTION[a] ?? {
    label: a,
    tone: (a.endsWith("approve") ? "green" : a.endsWith("reject") ? "red" : a.startsWith("event") ? "amber" : "blue") as Tone,
    icon: "list" as IconName,
  };

const val = (v: unknown) => (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v));

const ist = (iso: string) => {
  const d = new Date(iso);
  return {
    time: d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }),
    date: d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" }),
  };
};

export default function AuditPage() {
  const scenarioId = useScenarioId();
  const log = useApi<AuditEntry[]>(scenarioId ? `/audit?scenario_id=${scenarioId}&limit=500` : null);
  const [filter, setFilter] = useState("all");
  const toast = useToast();

  const rows = (log.data ?? []).filter((e) => filter === "all" || e.action === filter).reverse();
  const actions = [...new Set((log.data ?? []).map((e) => e.action))].sort();
  const people = (log.data ?? []).filter((e) => e.action.endsWith("approve") || e.action.endsWith("reject")).length;

  return (
    <>
      <PageHeader
        title="Audit log"
        purpose="An append-only record of every plan, event and decision in this scenario: who did it, when, and to what. Newest first, in IST."
        actions={
          scenarioId && (
            <>
              <Select label="Show" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-56">
                <option value="all">All actions</option>
                {actions.map((a) => <option key={a} value={a}>{action(a).label}</option>)}
              </Select>
              <div className="flex flex-col gap-1.5">
                <span className="select-none text-xs font-medium text-transparent" aria-hidden>Refresh</span>
                <Button
                  icon="refresh"
                  loading={log.loading && !!log.data}
                  onClick={() => { log.reload(); toast.info("Audit log refreshed"); }}
                >
                  Refresh
                </Button>
              </div>
            </>
          )
        }
      />
      <Gate scenarioId={scenarioId} error={log.error} ready={!!log.data} onRetry={log.reload} skeleton={<SkeletonTable rows={10} cols={5} />}>
        {() =>
          rows.length === 0 ? (
            <EmptyState icon="history" title="Nothing recorded yet">
              {filter === "all" ? "Generate or approve a plan and it appears here." : "No entries for this action."}
            </EmptyState>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-ink-3">
                <span className="tnum"><b className="font-semibold text-ink">{rows.length}</b> entries shown</span>
                <span className="flex items-center gap-1.5 tnum"><Icon name="user" size={14} /><b className="font-semibold text-ink">{people}</b> human decisions in total</span>
                <span className="flex items-center gap-1.5"><Icon name="lock" size={14} />Entries cannot be edited or deleted</span>
              </div>
              <Table head={["Time (IST)", "Action", "Object", "By", "Details"]}>
                {rows.map((e) => {
                  const a = action(e.action);
                  const t = ist(e.ts);
                  const human = !["system", "sim"].includes(e.actor.toLowerCase()) && !e.actor.startsWith("retask");
                  const details = Object.entries(e.details);
                  return (
                    <Tr key={e.id}>
                      <Td className="whitespace-nowrap">
                        <div className="font-medium text-ink tnum">{t.time}</div>
                        <div className="text-xs text-ink-3">{t.date}</div>
                      </Td>
                      <Td>
                        <Tooltip content={<span className="font-mono">{e.action}</span>}>
                          <span tabIndex={0}><Badge tone={a.tone} icon={a.icon} size="md">{a.label}</Badge></span>
                        </Tooltip>
                      </Td>
                      <Td>
                        <div className="text-xs text-ink-3">{e.object_type}</div>
                        <div className="font-mono text-xs text-ink">{e.object_id}</div>
                      </Td>
                      <Td>
                        <span className="inline-flex items-center gap-2">
                          <span className={`flex h-6 w-6 items-center justify-center rounded-full ${human ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-ink-3"}`}>
                            <Icon name={human ? "user" : "sparkle"} size={13} />
                          </span>
                          <span className="whitespace-nowrap text-[13px]">{e.actor}</span>
                        </span>
                      </Td>
                      <Td>
                        <div className="flex max-w-[560px] flex-wrap gap-1.5">
                          {details.slice(0, 6).map(([k, v]) => (
                            <span key={k} className="inline-flex max-w-[260px] items-baseline gap-1 rounded-md bg-subtle px-2 py-0.5 text-xs ring-1 ring-inset ring-line" title={`${k}: ${val(v)}`}>
                              <span className="text-ink-3">{k}</span>
                              <span className="truncate font-medium text-ink-2 tnum">{val(v)}</span>
                            </span>
                          ))}
                          {details.length > 6 && <span className="text-xs text-ink-4">+{details.length - 6} more</span>}
                        </div>
                      </Td>
                    </Tr>
                  );
                })}
              </Table>
            </>
          )
        }
      </Gate>
    </>
  );
}
