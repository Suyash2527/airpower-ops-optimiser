import type { Plan } from "@/lib/types";

export type Tone = "green" | "amber" | "red" | "blue" | "grey" | "violet";

/** Minutes from scenario start as T+hh:mm. */
export const tmin = (m: number) => {
  const sign = m < 0 ? "-" : "+";
  const a = Math.abs(Math.round(m));
  return `T${sign}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(a % 60).padStart(2, "0")}`;
};

/** Duration in minutes as "5 h 47 min". */
export const dur = (m: number) => {
  const a = Math.round(m);
  const h = Math.floor(a / 60);
  return h ? `${h} h ${String(a % 60).padStart(2, "0")} min` : `${a} min`;
};

/** Format an ISO UTC time in IST for display (time is UTC internally). */
export const ist = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }) + " IST";

/** Scenario t0 (UTC ISO) plus minutes, as an IST clock time. */
export const istAt = (t0: string, m: number) =>
  new Date(new Date(t0).getTime() + m * 60_000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }) + " IST";

export const pct = (v: number, digits = 0) => `${(v * 100).toFixed(digits)}%`;
export const signed = (v: number, digits = 2) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;

export const statusTone = (s: string): Tone =>
  s === "approved" ? "green" : s === "draft" || s === "open" ? "blue" : s === "superseded" || s === "expired" ? "grey" : s === "rejected" ? "red" : "amber";
export const riskTone = (v: number): Tone => (v < 0.2 ? "green" : v < 0.4 ? "amber" : "red");
export const riskWord = (v: number) => (v < 0.2 ? "Low" : v < 0.4 ? "Moderate" : "High");
export const healthTone = (s: string): Tone =>
  ["SERVICEABLE", "AVAILABLE"].includes(s) ? "green" : ["UNSERVICEABLE", "SICK"].includes(s) ? "red" : "amber";

/** Latest approved plan, else the newest plan. */
export const pickPlan = (plans: Plan[]) =>
  [...plans].reverse().find((p) => p.status === "approved") ?? plans[plans.length - 1] ?? null;

export const humanize = (s: string) => {
  const t = s.replaceAll("_", " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
