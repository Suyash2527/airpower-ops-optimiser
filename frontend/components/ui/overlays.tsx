"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon, type IconName } from "./Icon";

/* ---------------------------------------------------------------- shared: Escape + scroll lock */

function useOverlay(open: boolean, onClose: () => void) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => e.key === "Escape" && close.current();
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      document.body.style.overflow = prev;
    };
  }, [open]);
}

/* ---------------------------------------------------------------- Drawer */

export function Drawer({ open, onClose, title, subtitle, children, footer, width = 480 }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode; width?: number }) {
  useOverlay(open, onClose);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-ink/30 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" className="relative flex h-full w-full animate-slide-in-right flex-col bg-surface shadow-overlay" style={{ maxWidth: width }}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6 sm:py-5">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold leading-7 text-ink">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-ink-3">{subtitle}</p>}
          </div>
          <button onClick={onClose} aria-label="Close" className="-mr-2 rounded-md p-2 text-ink-3 transition-colors hover:bg-ink/5 hover:text-ink">
            <Icon name="x" size={18} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">{children}</div>
        {footer && <div className="border-t border-line bg-subtle px-6 py-4">{footer}</div>}
      </aside>
    </div>,
    document.body,
  );
}

/* ---------------------------------------------------------------- Modal */

export function Modal({ open, onClose, title, children, actions, icon = "info", tone = "blue" }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; actions: ReactNode; icon?: IconName; tone?: "blue" | "green" | "red" }) {
  useOverlay(open, onClose);
  if (!open) return null;
  const ring = tone === "green" ? "bg-emerald-50 text-emerald-600 ring-emerald-50/60" : tone === "red" ? "bg-red-50 text-red-600 ring-red-50/60" : "bg-brand-50 text-brand-600 ring-brand-50/60";
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 animate-fade-in bg-ink/40 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" className="relative w-full max-w-md animate-pop-in rounded-2xl bg-surface p-5 shadow-overlay sm:p-6">
        <span className={`flex h-11 w-11 items-center justify-center rounded-full ring-8 ${ring}`}>
          <Icon name={icon} size={20} />
        </span>
        <h2 className="mt-4 text-lg font-semibold text-ink">{title}</h2>
        <div className="mt-2 text-sm leading-6 text-ink-3">{children}</div>
        <div className="mt-6 flex flex-wrap justify-end gap-3">{actions}</div>
      </div>
    </div>,
    document.body,
  );
}

/* ---------------------------------------------------------------- Toasts */

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  body?: string;
}
const ToastCtx = createContext<(kind: ToastKind, title: string, body?: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (kind: ToastKind, title: string, body?: string) => {
      const id = next.current++;
      setItems((xs) => [...xs.slice(-3), { id, kind, title, body }]);
      setTimeout(() => dismiss(id), kind === "error" ? 9000 : 5500);
    },
    [dismiss],
  );

  return (
    <ToastCtx.Provider value={push}>
      {children}
      {items.length > 0 &&
        createPortal(
          <div className="pointer-events-none fixed bottom-4 right-4 z-[90] flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-3 sm:bottom-6 sm:right-6" aria-live="polite">
            {items.map((t) => (
              <div key={t.id} role="status" className="pointer-events-auto flex animate-toast-in items-start gap-3 rounded-xl border border-line bg-surface p-4 shadow-overlay">
                <Icon
                  name={t.kind === "success" ? "checkCircle" : t.kind === "error" ? "alert" : "info"}
                  size={20}
                  className={t.kind === "success" ? "text-emerald-600" : t.kind === "error" ? "text-red-600" : "text-brand-600"}
                />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-ink">{t.title}</div>
                  {t.body && <div className="mt-0.5 break-words text-[13px] leading-5 text-ink-3">{t.body}</div>}
                </div>
                <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="rounded p-0.5 text-ink-4 transition-colors hover:text-ink">
                  <Icon name="x" size={16} />
                </button>
              </div>
            ))}
          </div>,
          document.body,
        )}
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastCtx);
  return useMemo(
    () => ({
      success: (title: string, body?: string) => push("success", title, body),
      error: (title: string, body?: string) => push("error", title, body),
      info: (title: string, body?: string) => push("info", title, body),
    }),
    [push],
  );
}

/* ---------------------------------------------------------------- Tabs */

/** Measures the active child of `box` so an indicator can slide to it. */
function useIndicator(active: string) {
  const box = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<{ left: number; width: number } | null>(null);
  useLayoutEffect(() => {
    const el = box.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(active)}"]`);
    if (el) setRect({ left: el.offsetLeft, width: el.offsetWidth });
  }, [active]);
  return { box, rect };
}

export function Tabs<K extends string>({ tabs, value, onChange }: { tabs: { key: K; label: ReactNode; count?: number; icon?: IconName }[]; value: K; onChange: (k: K) => void }) {
  const { box, rect } = useIndicator(value);
  return (
    <div ref={box} role="tablist" className="relative flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]">
      {tabs.map((t) => {
        const on = t.key === value;
        return (
          <button
            key={t.key}
            data-key={t.key}
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.key)}
            className={`relative -mb-px flex shrink-0 items-center gap-2 whitespace-nowrap px-3 pb-3 pt-1 text-sm font-medium transition-colors ${on ? "text-brand-700" : "text-ink-3 hover:text-ink"}`}
          >
            {t.icon && <Icon name={t.icon} size={16} />}
            {t.label}
            {t.count !== undefined && (
              <span className={`rounded-full px-2 py-0.5 text-xs tnum transition-colors ${on ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-ink-3"}`}>{t.count}</span>
            )}
          </button>
        );
      })}
      {rect && (
        <span
          aria-hidden
          className="absolute -bottom-px h-0.5 rounded-full bg-brand-600 transition-[left,width] duration-300 ease-[var(--ease-out)]"
          style={{ left: rect.left, width: rect.width }}
        />
      )}
    </div>
  );
}

/** Segmented control for small filters, with a sliding thumb. */
export function Segmented<K extends string>({ options, value, onChange }: { options: { key: K; label: ReactNode }[]; value: K; onChange: (k: K) => void }) {
  const { box, rect } = useIndicator(value);
  return (
    <div ref={box} className="relative inline-flex max-w-full overflow-x-auto rounded-control border border-line bg-subtle p-0.5 [scrollbar-width:none]">
      {rect && (
        <span
          aria-hidden
          className="absolute inset-y-0.5 rounded-md bg-surface shadow-card transition-[left,width] duration-300 ease-[var(--ease-out)]"
          style={{ left: rect.left, width: rect.width }}
        />
      )}
      {options.map((o) => (
        <button
          key={o.key}
          data-key={o.key}
          onClick={() => onChange(o.key)}
          className={`relative shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${o.key === value ? "text-ink" : "text-ink-3 hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
