"use client";

import MapView from "@/components/MapView";
import { useApi, useScenarioId } from "@/lib/api";
import type { Snapshot } from "@/lib/types";
import { Card, ErrorBox, Loading, NeedScenario, PageHeader } from "@/components/ui";

export default function MapPage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);

  return (
    <>
      <PageHeader
        title="Operating picture"
        subtitle="Fused positions of bases, mission areas, threat zones and airspace restrictions, plotted by latitude and longitude. All objects except the alternate airfields are synthetic."
      />
      {!scenarioId ? (
        <NeedScenario />
      ) : snap.error ? (
        <ErrorBox message={snap.error} onRetry={snap.reload} />
      ) : !snap.data ? (
        <Loading what="map data" />
      ) : (
        <Card>
          <MapView snapshot={snap.data} />
        </Card>
      )}
    </>
  );
}
