"use client";

import MapView from "@/components/MapView";
import { useApi, useScenarioId } from "@/lib/api";
import type { Plan, Snapshot } from "@/lib/types";
import { Card, ErrorBox, Loading, NeedScenario, PageHeader, pickPlan } from "@/components/ui";

export default function MapPage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const plan = plans.data ? pickPlan(plans.data) : null;

  return (
    <>
      <PageHeader
        title="Operating picture"
        subtitle="Fused positions of bases, mission areas, threat zones, airspace restrictions and planned sorties. Move the time slider to see what is active when. All objects except the alternate airfields are synthetic."
      />
      {!scenarioId ? (
        <NeedScenario />
      ) : snap.error ? (
        <ErrorBox message={snap.error} onRetry={snap.reload} />
      ) : !snap.data ? (
        <Loading what="map data" />
      ) : (
        <Card>
          {plans.error && <ErrorBox message={`Plan routes unavailable: ${plans.error}`} onRetry={plans.reload} />}
          <MapView
            snapshot={snap.data}
            assignments={plan?.assignments ?? []}
            planLabel={plan ? `plan v${plan.version}, ${plan.status}` : undefined}
          />
        </Card>
      )}
    </>
  );
}
