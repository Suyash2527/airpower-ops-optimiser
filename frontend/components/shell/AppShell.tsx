"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useBusy } from "@/lib/busy";
import { useApi, useScenarioId } from "@/lib/api";
import type { ScenarioSummary } from "@/lib/types";
import { SEASONS } from "@/lib/labels";
import { Drawer, Icon, LogoMark, ToastProvider, Tooltip, type IconName } from "@/components/ui";

const NAV: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/scenario", label: "Scenario", icon: "database" },
  { href: "/map", label: "Operating picture", icon: "map" },
  { href: "/resources", label: "Fleet & crew", icon: "plane" },
  { href: "/plan", label: "Plan", icon: "clipboard" },
  { href: "/timeline", label: "Timeline", icon: "gantt" },
  { href: "/proposals", label: "Retasking", icon: "shuffle" },
  { href: "/audit", label: "Audit log", icon: "history" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const [about, setAbout] = useState(false);
  const path = usePathname();
  return (
    <ToastProvider>
      <div className="min-h-screen">
        <Sidebar />
        <div className="flex min-h-screen flex-col pl-64">
          <TopBar onAbout={() => setAbout(true)} />
          <main key={path} className="stagger mx-auto flex w-full max-w-[1360px] flex-1 flex-col gap-8 px-10 pb-16 pt-8">{children}</main>
        </div>
      </div>
      <BusyBar />
      <AboutDrawer open={about} onClose={() => setAbout(false)} />
    </ToastProvider>
  );
}

function Sidebar() {
  const path = usePathname();
  const nav = useRef<HTMLElement>(null);
  const [pill, setPill] = useState<{ top: number; height: number } | null>(null);
  useLayoutEffect(() => {
    const el = nav.current?.querySelector<HTMLElement>('[aria-current="page"]');
    setPill(el ? { top: el.offsetTop, height: el.offsetHeight } : null);
  }, [path]);
  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-line bg-surface">
      <Link href="/" className="flex h-16 items-center gap-3 border-b border-line px-5">
        <LogoMark size={32} />
        <div className="leading-tight">
          <div className="font-display text-[17px] font-semibold tracking-[-0.01em] text-ink">AirPower</div>
          <div className="text-[11px] font-medium text-ink-3">Air-ops decision support</div>
        </div>
      </Link>
      <nav ref={nav} className="relative flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-4" aria-label="Main">
        {pill && (
          <span
            aria-hidden
            className="absolute inset-x-3 rounded-lg bg-brand-50 transition-[top,height] duration-300 ease-[var(--ease-out)]"
            style={{ top: pill.top, height: pill.height }}
          >
            <span className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-brand-600" />
          </span>
        )}
        <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-4">Workflow</div>
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              aria-current={active ? "page" : undefined}
              className={`group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${active ? "text-brand-800" : "text-ink-2 hover:bg-subtle hover:text-ink"}`}
            >
              <Icon name={n.icon} size={18} className={active ? "text-brand-600" : "text-ink-4 transition-colors group-hover:text-ink-3"} />
              {n.label}
            </Link>
          );
        })}
      </nav>
      <div className="m-3 rounded-xl border border-line bg-subtle p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-ink">
          <Icon name="shield" size={16} className="text-brand-600" />
          Advisory only
        </div>
        <p className="mt-1 text-xs leading-5 text-ink-3">AirPower proposes. A human approves. Nothing changes a plan without an explicit approval.</p>
      </div>
    </aside>
  );
}

function TopBar({ onAbout }: { onAbout: () => void }) {
  const scenarioId = useScenarioId();
  const list = useApi<{ scenarios: ScenarioSummary[] }>(scenarioId ? `/scenarios?current=${scenarioId}` : null);
  const current = list.data?.scenarios.find((s) => s.scenario_id === scenarioId);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-line bg-surface/85 px-10 backdrop-blur-md">
      <div className="flex min-w-0 items-center gap-3">
        <span className="text-[13px] font-medium text-ink-3">Scenario</span>
        <Icon name="chevronRight" size={14} className="text-ink-4" />
        {scenarioId === undefined ? (
          <span className="skeleton h-4 w-40" />
        ) : current ? (
          <Link href="/scenario" className="flex min-w-0 items-center gap-2 rounded-md px-1.5 py-1 transition-colors hover:bg-subtle">
            <span className="truncate text-sm font-semibold capitalize text-ink">{current.name}</span>
            <span className="hidden whitespace-nowrap text-xs text-ink-3 xl:inline">
              · {SEASONS[current.season_preset] ?? current.season_preset} · seed {current.seed}
            </span>
          </Link>
        ) : scenarioId && !list.data && !list.error ? (
          <span className="skeleton h-4 w-40" />
        ) : (
          <Link href="/scenario" className="text-sm font-medium text-brand-700 hover:underline">No scenario loaded</Link>
        )}
      </div>
      <div className="ml-auto flex items-center gap-3">
        <Tooltip content="Every fleet, crew, mission, threat, weather and event record is synthetic, generated from a seed. Only base elevations, alternate airfields and the map outline come from open data.">
          <span tabIndex={0} className="inline-flex cursor-help items-center gap-1.5 whitespace-nowrap rounded-md bg-amber-400 px-2.5 py-1 text-[11px] font-bold tracking-[0.08em] text-amber-950 shadow-card">
            <Icon name="alert" size={13} strokeWidth={2.25} />
            SYNTHETIC DATA
          </span>
        </Tooltip>
        <IstClock />
        <button
          onClick={onAbout}
          className="inline-flex h-9 items-center gap-2 rounded-control border border-line-strong bg-surface px-3 text-[13px] font-medium text-ink-2 shadow-card transition-colors hover:bg-subtle hover:text-ink"
        >
          <Icon name="info" size={16} />
          About this prototype
        </button>
      </div>
    </header>
  );
}

function IstClock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  const time = now?.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const date = now?.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" });
  return (
    <Tooltip content="Wall-clock time in India Standard Time (UTC+05:30). The system stores all times in UTC.">
      <span className="inline-flex h-9 cursor-default items-center gap-2 rounded-control border border-line bg-subtle px-3 text-[13px] text-ink-2">
        <Icon name="clock" size={15} className="text-ink-3" />
        <span className="whitespace-nowrap font-semibold text-ink tnum">{time ?? "--:--:--"}</span>
        <span className="hidden text-ink-3 xl:inline">{date ?? ""}</span>
        <span className="text-ink-3">IST</span>
      </span>
    </Tooltip>
  );
}

function AboutDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="About this prototype"
      subtitle="Smart India Hackathon 2026 · problem SIH26250"
      width={520}
      footer={
        <div className="flex items-center gap-3">
          <LogoMark size={28} />
          <div className="text-sm font-semibold text-ink">AirPower proposes. A human approves.</div>
        </div>
      }
    >
      <div className="flex flex-col gap-6 text-sm leading-6 text-ink-2">
        <p>
          AirPower is a decision-support prototype for planning air operations. It brings scattered data into one picture,
          builds an allocation of aircraft, crew and loadouts to prioritised missions, and, when something changes, proposes
          ranked re-plans with reasons. It only allocates and schedules resources; it contains no targeting or weapon-employment logic.
        </p>
        <AboutSection icon="checkCircle" tone="text-emerald-600" title="What is real">
          <li>The planning methods actually run: feasibility checks, a CP-SAT optimiser (Google OR-Tools) and greedy and first-in first-out baselines.</li>
          <li>Every number on screen comes from the API for the current run; nothing is typed in by hand.</li>
          <li>Open data: the map outline (Natural Earth, public domain), alternate civil airfields (OurAirports) and base elevations (Open-Meteo).</li>
        </AboutSection>
        <AboutSection icon="alert" tone="text-amber-600" title="What is simulated">
          <li>All bases, units, tail numbers, aircraft types, crews, missions, threat zones, weather and events are synthetic and generated from a seed.</li>
          <li>The second data source is synthetic noise used to demonstrate fusion and conflict handling.</li>
          <li>Aircraft performance, duty limits, risk weights and scores are illustrative placeholders, not validated figures.</li>
        </AboutSection>
        <AboutSection icon="book" tone="text-brand-600" title="What real use would need">
          <li>Accredited live feeds for fleet status, crew rosters, weather, airspace and threat reporting.</li>
          <li>Validated aircraft performance data and rules reviewed by operators and doctrine owners.</li>
          <li>Security accreditation, access control and deployment on approved infrastructure.</li>
          <li>Trials with planners to measure speed and plan quality against current practice.</li>
        </AboutSection>
        <div className="rounded-xl border border-brand-200 bg-brand-50/60 p-4">
          <div className="flex items-center gap-2 font-semibold text-brand-900">
            <Icon name="shield" size={17} className="text-brand-600" />
            Human in the loop
          </div>
          <p className="mt-1 text-brand-900/85">
            Generated plans start as drafts, and re-plans are proposals. No code path applies a change on its own: a person
            approves each one, and every decision is written to the audit log.
          </p>
        </div>
      </div>
    </Drawer>
  );
}

function AboutSection({ icon, tone, title, children }: { icon: IconName; tone: string; title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="flex items-center gap-2 font-semibold text-ink">
        <Icon name={icon} size={17} className={tone} />
        {title}
      </h3>
      <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-6 marker:text-ink-4">{children}</ul>
    </section>
  );
}

/** Thin indeterminate bar at the top of the window while any action is running. */
function BusyBar() {
  const busy = useBusy();
  return (
    <div aria-hidden className={`pointer-events-none fixed inset-x-0 top-0 z-[95] h-[3px] overflow-hidden transition-opacity duration-300 ${busy ? "opacity-100" : "opacity-0"}`}>
      <div className="h-full w-full origin-left bg-gradient-to-r from-brand-400 via-brand-600 to-brand-400 [animation:indeterminate_1.4s_var(--ease-standard)_infinite]" />
    </div>
  );
}
