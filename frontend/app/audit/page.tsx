"use client";

import { useState } from "react";
import { useApi, useScenarioId } from "@/lib/api";
import type { AuditEntry } from "@/lib/types";
import { Badge, Button, Empty, ErrorBox, Loading, NeedScenario, PageHeader, Table, Td, ist, type Tone } from "@/components/ui";

const tone = (action: string): Tone =>
  action.endsWith("approve") ? "green" : action.endsWith("reject") ? "red" : action.startsWith("event") ? "amber" : action.endsWith("supersede") ? "grey" : "blue";

const summary = (d: Record<string, unknown>) =>
  Object.entries(d)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");

export default function AuditPage() {
  const scenarioId = useScenarioId();
  const log = useApi<AuditEntry[]>(scenarioId ? `/audit?scenario_id=${scenarioId}&limit=500` : null);
  const [action, setAction] = useState("all");

  const rows = (log.data ?? []).filter((e) => action === "all" || e.action === action).reverse();
  const actions = [...new Set((log.data ?? []).map((e) => e.action))].sort();

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Append-only record of every plan generation, approval, event and decision for this scenario. Newest first; times in IST."
        actions={
          scenarioId && (
            <>
              <select aria-label="Filter by action" className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm" value={action} onChange={(e) => setAction(e.target.value)}>
                <option value="all">All actions</option>
                {actions.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <Button onClick={log.reload}>Refresh</Button>
            </>
          )
        }
      />
      {!scenarioId ? (
        <NeedScenario />
      ) : log.error ? (
        <ErrorBox message={log.error} onRetry={log.reload} />
      ) : !log.data ? (
        <Loading what="audit log" />
      ) : rows.length === 0 ? (
        <Empty>No audit entries{action !== "all" ? ` for ${action}` : ""} yet.</Empty>
      ) : (
        <Table head={["Time", "Actor", "Action", "Object", "Details"]}>
          {rows.map((e) => (
            <tr key={e.id} className="hover:bg-slate-50">
              <Td className="whitespace-nowrap text-xs tabular-nums text-slate-600">{ist(e.ts)}</Td>
              <Td>{e.actor}</Td>
              <Td><Badge tone={tone(e.action)}>{e.action}</Badge></Td>
              <Td><span className="text-xs text-slate-500">{e.object_type}</span><br /><span className="font-mono text-xs">{e.object_id}</span></Td>
              <Td className="text-xs text-slate-700">{summary(e.details)}</Td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
