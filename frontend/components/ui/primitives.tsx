import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes, InputHTMLAttributes } from "react";
import { Icon, type IconName } from "./Icon";
import { Tooltip } from "./Tooltip";
import { CountUp } from "./CountUp";
import type { Tone } from "@/lib/format";

/* ---------------------------------------------------------------- Button */

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg";
const VARIANT: Record<Variant, string> = {
  primary: "bg-brand-600 text-white border-brand-600 hover:bg-brand-700 hover:border-brand-700 shadow-card",
  secondary: "bg-surface text-ink-2 border-line-strong hover:bg-subtle hover:text-ink shadow-card",
  ghost: "bg-transparent text-ink-2 border-transparent hover:bg-ink/5 hover:text-ink",
  danger: "bg-surface text-red-700 border-red-200 hover:bg-red-50 hover:border-red-300 shadow-card",
  success: "bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700 hover:border-emerald-700 shadow-card",
};
const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-5 text-[15px] gap-2.5",
};

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  iconRight,
  loading = false,
  className = "",
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; icon?: IconName; iconRight?: IconName; loading?: boolean }) {
  return (
    <button
      disabled={disabled || loading}
      className={`press inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-control border font-medium focus-visible:shadow-focus focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-55 ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...props}
    >
      {loading ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden /> : icon && <Icon name={icon} size={size === "lg" ? 18 : 16} />}
      {children}
      {iconRight && <Icon name={iconRight} size={16} />}
    </button>
  );
}

export function IconButton({ icon, label, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string }) {
  return (
    <Tooltip content={label}>
      <button
        aria-label={label}
        className={`press inline-flex h-9 w-9 items-center justify-center rounded-control border border-line-strong bg-surface text-ink-2 shadow-card hover:bg-subtle hover:text-ink focus-visible:shadow-focus focus-visible:outline-none ${className}`}
        {...props}
      >
        <Icon name={icon} size={17} />
      </button>
    </Tooltip>
  );
}

/* ---------------------------------------------------------------- Card */

export function Card({ children, className = "", padded = true }: { children: ReactNode; className?: string; padded?: boolean }) {
  return <section className={`min-w-0 rounded-card border border-line bg-surface shadow-card ${padded ? "p-4 sm:p-6" : ""} ${className}`}>{children}</section>;
}

export function CardHeader({ title, subtitle, actions, icon, className = "" }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; icon?: IconName; className?: string }) {
  return (
    <div className={`flex flex-wrap items-start justify-between gap-x-4 gap-y-2 ${className}`}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
            <Icon name={icon} size={17} />
          </span>
        )}
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold leading-6 text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-[13px] leading-5 text-ink-3">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- Badge, StatusDot */

const BADGE: Record<Tone, string> = {
  green: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/25",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  blue: "bg-brand-50 text-brand-800 ring-brand-600/20",
  grey: "bg-slate-100 text-ink-2 ring-slate-500/15",
  violet: "bg-violet-50 text-violet-800 ring-violet-600/20",
};
const DOT: Record<Tone, string> = {
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-red-500",
  blue: "bg-brand-500",
  grey: "bg-slate-400",
  violet: "bg-violet-500",
};

export function Badge({ tone = "grey", children, icon, dot = false, className = "", size = "sm" }: { tone?: Tone; children: ReactNode; icon?: IconName; dot?: boolean; className?: string; size?: "sm" | "md" }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full font-medium ring-1 ring-inset tnum ${size === "md" ? "px-2.5 py-1 text-xs" : "px-2 py-0.5 text-xs"} ${BADGE[tone]} ${className}`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${DOT[tone]}`} />}
      {icon && <Icon name={icon} size={12} strokeWidth={2} />}
      {children}
    </span>
  );
}

export function StatusDot({ tone, label, pulse = false }: { tone: Tone; label?: ReactNode; pulse?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap text-[13px] text-ink-2">
      <span className="relative flex h-2 w-2">
        {pulse && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${DOT[tone]}`} />}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${DOT[tone]}`} />
      </span>
      {label}
    </span>
  );
}

/** Mission priority chip: one ordinal hue, darkest = priority 1. */
export function PriorityChip({ p, compact = false }: { p: number; compact?: boolean }) {
  const light = p >= 4;
  return (
    <Tooltip content={`Priority ${p} of 5 (1 is the most important).`}>
      <span
        className={`inline-flex items-center justify-center rounded-md font-semibold tnum ${compact ? "h-5 min-w-6 px-1 text-[11px]" : "h-6 min-w-8 px-1.5 text-xs"} ${light ? "text-p1" : "text-white"}`}
        style={{ background: `var(--color-p${Math.min(5, Math.max(1, p))})` }}
      >
        P{p}
      </span>
    </Tooltip>
  );
}

/* ---------------------------------------------------------------- Page header */

export function PageHeader({ title, purpose, actions, eyebrow }: { title: string; purpose: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 max-w-2xl">
        {eyebrow && <div className="mb-1 text-xs font-semibold uppercase tracking-[0.08em] text-brand-700">{eyebrow}</div>}
        <h1 className="font-display text-2xl font-semibold leading-8 tracking-[-0.01em] text-ink sm:text-[28px] sm:leading-9">{title}</h1>
        <p className="mt-1.5 text-sm leading-6 text-ink-3 sm:text-[15px]">{purpose}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/* ---------------------------------------------------------------- KPI card */

export function KpiCard({
  label,
  value,
  unit,
  meaning,
  icon,
  tone,
  footer,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  meaning: ReactNode;
  icon?: IconName;
  tone?: Tone;
  footer?: ReactNode;
}) {
  return (
    <div className="lift flex min-w-0 flex-col rounded-card border border-line bg-surface p-4 shadow-card sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-ink-3">{label}</span>
        {icon && (
          <span className={`flex h-7 w-7 items-center justify-center rounded-md ${tone ? BADGE[tone] : "bg-slate-100 text-ink-3"}`}>
            <Icon name={icon} size={15} />
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="font-display text-[26px] font-semibold leading-9 sm:text-[30px] tracking-[-0.01em] text-ink tnum">{typeof value === "string" || typeof value === "number" ? <CountUp value={value} /> : value}</span>
        {unit && <span className="text-sm font-medium text-ink-3">{unit}</span>}
      </div>
      <p className="mt-1 text-[13px] leading-5 text-ink-3">{meaning}</p>
      {footer && <div className="mt-3 border-t border-line pt-3">{footer}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- Empty / error states */

export function EmptyState({ icon = "info", title, children, action }: { icon?: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-line-strong bg-surface px-4 py-10 text-center sm:px-6 sm:py-14">
      <span className="enter-pop flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-700 ring-8 ring-brand-50/50">
        <Icon name={icon} size={22} />
      </span>
      <h3 className="mt-4 text-base font-semibold text-ink">{title}</h3>
      {children && <p className="mt-1 max-w-md text-sm leading-6 text-ink-3">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-card border border-red-200 bg-red-50/70 p-4 text-sm text-red-800">
      <Icon name="alert" size={18} className="mt-0.5 text-red-600" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">Something went wrong</div>
        <div className="mt-0.5 break-words text-red-700">{message}</div>
      </div>
      {onRetry && <Button size="sm" icon="refresh" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

/* ---------------------------------------------------------------- Callout / banner */

const CALLOUT: Record<Tone, string> = {
  blue: "border-brand-200 bg-brand-50/70 text-brand-900 [&_svg]:text-brand-600",
  amber: "border-amber-200 bg-amber-50/80 text-amber-900 [&_svg]:text-amber-600",
  green: "border-emerald-200 bg-emerald-50/80 text-emerald-900 [&_svg]:text-emerald-600",
  red: "border-red-200 bg-red-50/80 text-red-900 [&_svg]:text-red-600",
  grey: "border-line bg-subtle text-ink-2 [&_svg]:text-ink-3",
  violet: "border-violet-200 bg-violet-50 text-violet-900 [&_svg]:text-violet-600",
};
export function Callout({ tone = "blue", icon = "info", title, children, action }: { tone?: Tone; icon?: IconName; title?: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={`flex items-start gap-3 rounded-card border px-4 py-3 text-sm leading-6 ${CALLOUT[tone]}`}>
      <Icon name={icon} size={18} className="mt-[3px]" />
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={title ? "opacity-90" : ""}>{children}</div>}
      </div>
      {action}
    </div>
  );
}

/* ---------------------------------------------------------------- Skeletons */

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function SkeletonCards({ n = 4 }: { n?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:[grid-template-columns:repeat(var(--n),minmax(0,1fr))]" style={{ ["--n" as string]: n }}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="rounded-card border border-line bg-surface p-5 shadow-card">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="mt-4 h-8 w-20" />
          <Skeleton className="mt-3 h-3 w-40" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface shadow-card" role="status" aria-label="Loading">
      <div className="flex gap-6 border-b border-line bg-subtle px-5 py-3.5">
        {Array.from({ length: cols }, (_, i) => <Skeleton key={i} className="h-3 flex-1" />)}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-6 border-b border-line px-5 py-4 last:border-0">
          {Array.from({ length: cols }, (_, i) => <Skeleton key={i} className={`h-3.5 flex-1 ${i === 0 ? "max-w-24" : ""}`} />)}
        </div>
      ))}
    </div>
  );
}

export function PageSkeleton({ kpis = 4, rows = 8 }: { kpis?: number; rows?: number }) {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading">
      {kpis > 0 && <SkeletonCards n={kpis} />}
      <SkeletonTable rows={rows} />
    </div>
  );
}

/* ---------------------------------------------------------------- Table */

export function Table({ head, children, className = "", dense = false }: { head: ReactNode[]; children: ReactNode; className?: string; dense?: boolean }) {
  return (
    <div className={`overflow-x-auto rounded-card border border-line bg-surface shadow-card ${className}`}>
      <table className={`min-w-full text-left text-sm ${dense ? "[&_td]:py-2.5" : ""}`}>
        <thead>
          <tr className="border-b border-line bg-subtle">
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-4 py-3 text-xs font-semibold text-ink-3 first:pl-5 last:pr-5">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="stagger divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export const Tr = ({ children, className = "", onClick, selected = false }: { children: ReactNode; className?: string; onClick?: () => void; selected?: boolean }) => (
  <tr onClick={onClick} className={`transition-colors ${selected ? "bg-brand-50/60" : "hover:bg-subtle"} ${onClick ? "cursor-pointer" : ""} ${className}`}>{children}</tr>
);

export const Td = ({ children, className = "", colSpan }: { children?: ReactNode; className?: string; colSpan?: number }) => (
  <td colSpan={colSpan} className={`px-4 py-3.5 align-middle text-ink-2 first:pl-5 last:pr-5 ${className}`}>{children}</td>
);

/* ---------------------------------------------------------------- Form controls */

const CONTROL = "h-10 rounded-control border border-line-strong bg-surface px-3 text-sm text-ink shadow-card transition-colors hover:border-ink-4 focus:border-brand-500 focus:shadow-focus focus:outline-none";

export function Select({ label, className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  const el = (
    <span className="relative inline-flex max-w-full">
      <select className={`${CONTROL} appearance-none pr-9 ${className}`} aria-label={label} {...props}>{children}</select>
      <Icon name="chevronDown" size={16} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-3" />
    </span>
  );
  if (!label) return el;
  return (
    <label className="inline-flex min-w-0 max-w-full flex-col gap-1.5">
      <span className="text-xs font-medium text-ink-3">{label}</span>
      {el}
    </label>
  );
}

export function NumberField({ label, className = "", ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="inline-flex flex-col gap-1.5">
      <span className="text-xs font-medium text-ink-3">{label}</span>
      <input type="number" className={`${CONTROL} w-28 tnum ${className}`} {...props} />
    </label>
  );
}

/** Description list row used in detail panels. */
export function DetailRows({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-line">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 py-2.5 text-sm">
          <dt className="shrink-0 text-ink-3">{k}</dt>
          <dd className="text-right font-medium text-ink tnum">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Thin horizontal bar for a 0..1 share. */
export function Meter({ value, color = "var(--color-brand-500)", className = "" }: { value: number; color?: string; className?: string }) {
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-slate-100 ${className}`}>
      <div className="enter-grow-x h-full rounded-full transition-[width] duration-300" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }} />
    </div>
  );
}
