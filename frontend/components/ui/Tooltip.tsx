"use client";

import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Hover/focus tooltip rendered in a portal with fixed positioning, so it is never clipped by a
 * scrolling table or a card with overflow hidden. Flips below the trigger when there is no room above.
 */
export function Tooltip({ content, children, className = "", maxWidth = 300 }: { content: ReactNode; children: ReactNode; className?: string; maxWidth?: number }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number; below: boolean } | null>(null);
  const trigger = useRef<HTMLSpanElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const id = useId();

  useLayoutEffect(() => {
    if (!open || !trigger.current || !tip.current) return;
    const r = trigger.current.getBoundingClientRect();
    const t = tip.current.getBoundingClientRect();
    const below = r.top - t.height - 8 < 8;
    const x = Math.min(Math.max(8, r.left + r.width / 2 - t.width / 2), window.innerWidth - t.width - 8);
    setPos({ x, y: below ? r.bottom + 8 : r.top - t.height - 8, below });
  }, [open]);

  if (!content) return <>{children}</>;
  return (
    <span
      ref={trigger}
      className={`inline-flex ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => { setOpen(false); setPos(null); }}
      onFocus={() => setOpen(true)}
      onBlur={() => { setOpen(false); setPos(null); }}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open &&
        createPortal(
          <div
            ref={tip}
            id={id}
            role="tooltip"
            style={{ left: pos?.x ?? -9999, top: pos?.y ?? -9999, maxWidth }}
            className="pointer-events-none fixed z-[100] animate-fade-in rounded-lg bg-ink px-3 py-2 text-xs leading-5 text-white shadow-overlay"
          >
            {content}
          </div>,
          document.body,
        )}
    </span>
  );
}
