const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:5050/api/v1";

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: init?.method ?? "GET",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    body: init?.body ? JSON.stringify(init.body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${path}: ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

const KEY = "airpower.scenario_id";
export const getScenarioId = (): string | null => {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
};
export const setScenarioId = (id: string): void => {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* storage unavailable: page still works for this load */
  }
};

export interface ScenarioSummary {
  scenario_id: string;
  name: string;
  seed: number;
  horizon_min: number;
  season_preset: string;
  counts: Record<string, number>;
  data_label: string;
}
