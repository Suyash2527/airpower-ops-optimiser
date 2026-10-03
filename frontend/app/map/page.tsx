"use client";

import MapView from "@/components/MapView";
import { useApi, useScenarioId } from "@/lib/api";
import type { Plan, Snapshot } from "@/lib/types";
import { pickPlan } from "@/lib/format";
import { PageHeader, Skeleton } from "@/components/ui";
import { Gate } from "@/components/shell/states";

export default function MapPage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const plan = plans.data ? pickPlan(plans.data) : null;

  return (
    <>
      <PageHeader
        title="Operating picture"
        purpose="Everything the planner needs on one map: bases, mission areas, threat zones, airspace restrictions and planned sorties. Move the time slider to see what is active when."
      />
      <Gate
        scenarioId={scenarioId}
        error={snap.error ?? plans.error}
        ready={!!snap.data && !!plans.data}
        onRetry={() => { snap.reload(); plans.reload(); }}
        skeleton={
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]" role="status" aria-label="Loading">
            <Skeleton className="h-[60vh] min-h-[360px] !rounded-card lg:h-[calc(100vh-260px)] lg:min-h-[640px]" />
            <div className="flex flex-col gap-6"><Skeleton className="h-80 !rounded-card" /><Skeleton className="h-48 !rounded-card" /></div>
          </div>
        }
      >
        {() => (
          <MapView
            snapshot={snap.data!}
            assignments={plan?.assignments ?? []}
            planLabel={plan ? `plan v${plan.version} (${plan.status === "approved" ? "active" : plan.status})` : undefined}
          />
        )}
      </Gate>
    </>
  );
}
