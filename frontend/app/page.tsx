"use client";

import Link from "next/link";
import { useApi, useScenarioId } from "@/lib/api";
import type { Plan, Proposal, ScenarioSummary } from "@/lib/types";
import { SEASONS } from "@/lib/labels";
import { pickPlan, plural } from "@/lib/format";
import { Badge, Button, Icon, Skeleton, StatusDot, type IconName } from "@/components/ui";

const STEPS: { icon: IconName; title: string; text: string; page: string; human?: boolean }[] = [
  { icon: "database", title: "Load a scenario", text: "A seeded synthetic picture of bases, fleet, crew, missions, threats and weather.", page: "Scenario" },
  { icon: "layers", title: "Fuse the sources", text: "One record per asset, with its source, its age and any disagreement between feeds.", page: "Fleet & crew" },
  { icon: "map", title: "See the picture", text: "Bases, mission areas, threat zones and airspace on one map, over time.", page: "Operating picture" },
  { icon: "zap", title: "Generate a plan", text: "An optimiser assigns aircraft, crew and loadouts, with a reason for every choice.", page: "Plan" },
  { icon: "user", title: "Approve the plan", text: "A planner reviews the draft. It becomes active only on approval.", page: "Plan", human: true },
  { icon: "shuffle", title: "Re-plan on disruption", text: "When an aircraft, crew, weather or threat changes, ranked repair options with a plan diff.", page: "Retasking" },
  { icon: "history", title: "Decide and record", text: "A planner approves or rejects each option. Every decision is in the audit log.", page: "Audit log", human: true },
];

export default function HomePage() {
  return (
    <>
      <Hero />
      <Workflow />
      <Principles />
    </>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden rounded-[20px] border border-line bg-surface shadow-card">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.55]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 85% 20%, var(--color-brand-100), transparent 45%), linear-gradient(var(--color-line) 1px, transparent 1px), linear-gradient(90deg, var(--color-line) 1px, transparent 1px)",
          backgroundSize: "100% 100%, 40px 40px, 40px 40px",
          maskImage: "linear-gradient(90deg, transparent 30%, black 80%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 -top-32 h-[420px] w-[520px] rounded-full opacity-60 blur-3xl [animation:aurora_14s_ease-in-out_infinite]"
        style={{ background: "radial-gradient(circle, var(--color-brand-200), transparent 65%)" }}
      />
      <div className="relative grid gap-8 p-6 sm:p-10 lg:grid-cols-[1fr_380px] lg:gap-10 lg:p-12">
        <div className="stagger max-w-2xl">
          <Badge tone="blue" size="md" icon="shield">Advisory decision-support prototype</Badge>
          <h1 className="mt-5 font-display text-5xl font-semibold tracking-[-0.02em] text-ink sm:text-display">AirPower</h1>
          <p className="mt-3 text-lg leading-7 text-ink-2 sm:text-xl sm:leading-8">
            Plan air operations from one fused picture and get ranked re-plan options the moment something changes, with a
            reason for every decision and a person approving every change.
          </p>
          <div className="mt-8 flex flex-wrap gap-3 [&>a]:flex-1 sm:[&>a]:flex-none [&_button]:w-full">
            <Link href="/scenario"><Button variant="primary" size="lg" icon="database">Scenario</Button></Link>
            <Link href="/map"><Button size="lg" icon="map">Operating picture</Button></Link>
            <Link href="/plan"><Button size="lg" icon="clipboard">Plan</Button></Link>
          </div>
        </div>
        <SessionCard />
      </div>
    </section>
  );
}

/** Live summary of the current session, read from the API. */
function SessionCard() {
  const scenarioId = useScenarioId();
  const list = useApi<{ scenarios: ScenarioSummary[] }>(scenarioId ? `/scenarios?current=${scenarioId}` : null);
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const proposals = useApi<Proposal[]>(scenarioId ? `/proposals?scenario_id=${scenarioId}` : null);
  const s = list.data?.scenarios.find((x) => x.scenario_id === scenarioId);
  const active = plans.data ? [...plans.data].reverse().find((p) => p.status === "approved") : undefined;
  const latest = plans.data ? pickPlan(plans.data) : null;
  const open = proposals.data?.filter((p) => p.status === "open").length ?? 0;
  const loading = scenarioId === undefined || (scenarioId && (!list.data || !plans.data || !proposals.data) && !list.error);

  return (
    <div className="enter-rise self-start rounded-2xl border border-line bg-surface/90 p-6 shadow-raised backdrop-blur" style={{ ["--d" as string]: 250 }}>
      <div className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-4">Current session</div>
      {loading ? (
        <div className="mt-4 flex flex-col gap-3">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-3/5" />
        </div>
      ) : !s ? (
        <div className="mt-3">
          <div className="text-base font-semibold text-ink">No scenario loaded</div>
          <p className="mt-1 text-sm leading-6 text-ink-3">Start by loading the demo scenario. It takes a second and everything else follows from it.</p>
          <Link href="/scenario" className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline">
            Go to Scenario <Icon name="arrowRight" size={15} />
          </Link>
        </div>
      ) : (
        <>
          <div className="mt-3 text-base font-semibold capitalize text-ink">{s.name}</div>
          <div className="mt-0.5 text-[13px] text-ink-3">{SEASONS[s.season_preset] ?? s.season_preset} · seed {s.seed}</div>
          <dl className="mt-4 divide-y divide-line text-sm">
            <Row k="Fleet" v={`${plural(s.counts.aircraft ?? 0, "aircraft", "aircraft")} at ${plural(s.counts.bases ?? 0, "base")}`} />
            <Row k="Missions" v={plural(s.counts.missions ?? 0, "mission")} />
            <Row
              k="Active plan"
              v={active ? <StatusDot tone="green" label={`v${active.version} approved`} /> : latest ? <StatusDot tone="blue" label={`v${latest.version} draft`} /> : <span className="text-ink-3">none yet</span>}
            />
            <Row k="Open proposals" v={open ? <StatusDot tone="amber" pulse label={plural(open, "option")} /> : <span className="text-ink-3">none</span>} />
          </dl>
        </>
      )}
    </div>
  );
}

const Row = ({ k, v }: { k: string; v: React.ReactNode }) => (
  <div className="flex items-center justify-between gap-4 py-2.5">
    <dt className="text-ink-3">{k}</dt>
    <dd className="font-medium text-ink tnum">{v}</dd>
  </div>
);

function Workflow() {
  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-display text-xl font-semibold text-ink">How it works</h2>
          <p className="mt-1 text-[15px] text-ink-3">Seven steps from raw data to an approved, audited plan. Two of them are always a person&apos;s decision.</p>
        </div>
        <div className="flex items-center gap-4 text-[13px] text-ink-3">
          <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full border-2 border-brand-500 bg-surface" /> System step</span>
          <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full bg-amber-500" /> Human decision</span>
        </div>
      </div>
      <ol className="mt-6 grid grid-cols-1 gap-x-4 gap-y-8 sm:grid-cols-2 md:grid-cols-4 xl:grid-cols-7 xl:gap-0">
        {STEPS.map((s, i) => (
          <li key={s.title} className="enter-rise relative flex flex-col items-center px-2 text-center" style={{ ["--d" as string]: 200 + i * 110 }}>
            {i < STEPS.length - 1 && (
              <span aria-hidden className="enter-grow-x absolute hidden xl:flex left-[calc(50%+30px)] right-[calc(-50%+30px)] top-[27px] flex items-center" style={{ ["--d" as string]: 320 + i * 110 }}>
                <span className="h-px flex-1 bg-line-strong" />
                <Icon name="chevronRight" size={14} className="-ml-1 text-ink-4" />
              </span>
            )}
            <span
              className={`relative flex h-14 w-14 items-center justify-center rounded-2xl shadow-card ${s.human ? "bg-amber-500 text-white" : "border border-brand-200 bg-surface text-brand-600"}`}
            >
              <Icon name={s.icon} size={24} />
              <span className={`absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold tnum ring-2 ring-canvas ${s.human ? "bg-amber-950 text-white" : "bg-brand-700 text-white"}`}>
                {i + 1}
              </span>
            </span>
            <h3 className="mt-4 text-sm font-semibold text-ink">{s.title}</h3>
            <p className="mt-1 flex-1 text-[13px] leading-5 text-ink-3">{s.text}</p>
            <span className={`mt-3 rounded-full px-2 py-0.5 text-[11px] font-medium ${s.human ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-ink-3"}`}>{s.page}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Principles() {
  const items: { icon: IconName; title: string; text: string }[] = [
    { icon: "shield", title: "Advisory only", text: "The system proposes and a person approves. Nothing is applied automatically, and there is no targeting or weapon-employment logic." },
    { icon: "alert", title: "Synthetic data, clearly labelled", text: "All operational data is generated from a seed. The same seed always gives the same scenario and the same result." },
    { icon: "list", title: "Every decision explained", text: "Each assignment, rejection and re-plan carries reason codes and a plain sentence. Hover any reason to read it." },
  ];
  return (
    <section className="stagger grid grid-cols-1 gap-4 sm:gap-6 md:grid-cols-3">
      {items.map((it) => (
        <div key={it.title} className="lift rounded-card border border-line bg-surface p-6 shadow-card">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-700"><Icon name={it.icon} size={20} /></span>
          <h3 className="mt-4 text-[15px] font-semibold text-ink">{it.title}</h3>
          <p className="mt-1.5 text-sm leading-6 text-ink-3">{it.text}</p>
        </div>
      ))}
    </section>
  );
}
