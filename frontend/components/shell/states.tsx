"use client";

import Link from "next/link";
import { useCallback, useState, type ReactNode } from "react";
import { Button, EmptyState, ErrorState, PageSkeleton, useToast } from "@/components/ui";
import { busyEnd, busyStart } from "@/lib/busy";

/** Shown when no scenario is chosen yet. */
export function NeedScenario() {
  return (
    <EmptyState
      icon="database"
      title="No scenario loaded"
      action={
        <Link href="/scenario">
          <Button variant="primary" iconRight="arrowRight">Choose a scenario</Button>
        </Link>
      }
    >
      Load the demo scenario or generate a seeded synthetic one. Every page reads from the scenario you choose.
    </EmptyState>
  );
}

/**
 * Standard page body states, in order: scenario unknown (hydrating) → skeleton; no scenario → prompt;
 * error → retry; loading → skeleton; else the content.
 */
export function Gate({
  scenarioId,
  error,
  ready,
  onRetry,
  skeleton,
  children,
}: {
  scenarioId: string | null | undefined;
  error?: string | null;
  ready: boolean;
  onRetry?: () => void;
  skeleton?: ReactNode;
  children: () => ReactNode;
}) {
  const sk = skeleton ?? <PageSkeleton />;
  if (scenarioId === undefined) return <>{sk}</>;
  if (scenarioId === null) return <NeedScenario />;
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (!ready) return <>{sk}</>;
  // Content replaces the skeleton with the page's rhythm: sections rise in order.
  return <div className="stagger flex flex-col gap-8">{children()}</div>;
}

/** Run an async action with a busy flag and a toast for the result (success or failure). */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(
    async <T,>(label: string, fn: () => Promise<T>, ok: (r: T) => [string, string?], failTitle = "Action failed") => {
      setBusy(label);
      busyStart();
      try {
        const r = await fn();
        const [title, body] = ok(r);
        toast.success(title, body);
        return r;
      } catch (e) {
        toast.error(failTitle, (e as Error).message);
        return null;
      } finally {
        busyEnd();
        setBusy(null);
      }
    },
    [toast],
  );
  return { busy, run };
}
