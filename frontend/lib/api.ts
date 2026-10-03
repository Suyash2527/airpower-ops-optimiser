"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

// Dev talks to the local API on 5050 (D-63); a production build defaults to the same origin, where
// vercel.json routes /api/* to the FastAPI service (D-66). NEXT_PUBLIC_API_URL overrides both.
const BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production" ? "/api/v1" : "http://localhost:5050/api/v1");

// ---------------------------------------------------------------------- state cache (D-72)
// Serverless instances do not share a database, so the browser keeps the signed state bundle the
// API returns after every write and re-uploads it when an instance reports it is out of sync.
interface StateBundle {
  scenario_id: string;
  rev: string;
  [k: string]: unknown;
}
const STATE_KEY = (sid: string) => `airpower.state.${sid}`;

function readBundle(sid: string): StateBundle | null {
  try {
    const raw = localStorage.getItem(STATE_KEY(sid));
    return raw ? (JSON.parse(raw) as StateBundle) : null;
  } catch {
    return null;
  }
}

function writeBundle(bundle: StateBundle): void {
  try {
    // One scenario at a time keeps us well inside the localStorage quota.
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k?.startsWith("airpower.state.") && k !== STATE_KEY(bundle.scenario_id)) localStorage.removeItem(k);
    }
    localStorage.setItem(STATE_KEY(bundle.scenario_id), JSON.stringify(bundle));
  } catch {
    /* storage full or blocked: works while requests land on the same instance */
  }
}

function dropBundle(sid: string): void {
  try {
    localStorage.removeItem(STATE_KEY(sid));
  } catch {
    /* storage unavailable */
  }
}

/**
 * The server would not take our cached state back (signed by an older deployment's secret, or a
 * scenario it cannot rebuild). Decide what the user ends up with.
 */
function onRestoreFailed(sid: string, status: number, message: string): void {
  // TODO(you): choose the recovery policy. Default: forget the cached copy so the page keeps
  // working against whatever this instance has (plans made earlier may be gone).
  console.warn(`state restore refused (${status}): ${message}`);
  dropBundle(sid);
}

// Parallel requests that all hit a fresh instance share one restore.
const restoring = new Map<string, Promise<void>>();

function restore(sid: string, bundle: StateBundle): Promise<void> {
  let p = restoring.get(sid);
  if (!p) {
    p = fetch(`${BASE}/sync/restore`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bundle),
    })
      .then(async (r) => {
        if (!r.ok) onRestoreFailed(sid, r.status, (await r.text()).slice(0, 300));
      })
      .finally(() => restoring.delete(sid));
    restoring.set(sid, p);
  }
  return p;
}

async function send(path: string, init?: { method?: string; body?: unknown }): Promise<Response> {
  const sid = getScenarioId();
  const bundle = sid ? readBundle(sid) : null;
  const headers: Record<string, string> = { "X-AirPower-Sync": "1" };
  if (init?.body) headers["Content-Type"] = "application/json";
  if (sid) headers["X-AirPower-Scenario"] = sid;
  if (bundle) headers["X-AirPower-Rev"] = bundle.rev;
  try {
    return await fetch(`${BASE}${path}`, {
      method: init?.method ?? "GET",
      headers,
      body: init?.body ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new Error(`Cannot reach the API at ${BASE}. Is the backend running (scripts/dev.ps1)?`);
  }
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res = await send(path, init);
  if (res.status === 409) {
    const sid = getScenarioId();
    const bundle = sid ? readBundle(sid) : null;
    const code = await res.clone().json().then((b) => b?.error?.code, () => null);
    if (code === "state_out_of_sync" && sid && bundle) {
      await restore(sid, bundle);
      res = await send(path, init);
    }
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
  if (res.headers.get("X-AirPower-Envelope") === "1") {
    const { data, state } = (await res.json()) as { data: T; state: StateBundle };
    writeBundle(state);
    return data;
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
/** Forget the current scenario (e.g. the server no longer has it). */
export const clearScenarioId = (): void => {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event(CHANGED));
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
      (e: Error) => {
        // The server lost or never had this scenario (a reset database): drop the stale id so
        // pages show "No scenario loaded" instead of an error.
        const sid = getScenarioId();
        if (sid && / 404 /.test(` ${e.message}`) && e.message.includes(`unknown scenario: ${sid}`)) {
          clearScenarioId();
          return;
        }
        if (live) setState({ key, data: null, error: e.message });
      },
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
