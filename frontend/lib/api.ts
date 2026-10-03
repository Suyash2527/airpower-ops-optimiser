"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:5050/api/v1";

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: init?.method ?? "GET",
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
      body: init?.body ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new Error(`Cannot reach the API at ${BASE}. Is the backend running (scripts/dev.ps1)?`);
  }
  if (!res.ok) {
    const text = await res.text();
    let message = text.slice(0, 300);
    try {
      const body = JSON.parse(text) as { error?: { message?: string }; detail?: unknown };
      message = body.error?.message ?? (typeof body.detail === "string" ? body.detail : message);
    } catch {
      /* not JSON: keep the raw text */
    }
    throw new Error(`${res.status} ${path}: ${message}`);
  }
  return res.json() as Promise<T>;
}

const KEY = "airpower.scenario_id";
const CHANGED = "airpower:scenario";

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
  window.dispatchEvent(new Event(CHANGED));
};

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(CHANGED, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(CHANGED, cb);
  };
}

/**
 * Current scenario id: `undefined` while rendering on the server and during hydration (not known
 * yet, so pages show skeletons instead of flashing "no scenario"), `null` when none is chosen.
 */
export function useScenarioId(): string | null | undefined {
  return useSyncExternalStore(subscribe, getScenarioId, () => undefined);
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** GET `path` (skipped while null) and track loading / error state. */
export function useApi<T>(path: string | null): Loaded<T> {
  const [state, setState] = useState<{ key: string | null; data: T | null; error: string | null }>({
    key: null,
    data: null,
    error: null,
  });
  const [tick, setTick] = useState(0);
  const key = path ? `${path}#${tick}` : null;

  useEffect(() => {
    if (!path || !key) return;
    let live = true;
    api<T>(path).then(
      (data) => live && setState({ key, data, error: null }),
      (e: Error) => live && setState({ key, data: null, error: e.message }),
    );
    return () => {
      live = false;
    };
  }, [path, key]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const fresh = state.key === key;
  return {
    data: path ? state.data : null,
    error: fresh ? state.error : null,
    loading: path !== null && !fresh,
    reload,
  };
}
