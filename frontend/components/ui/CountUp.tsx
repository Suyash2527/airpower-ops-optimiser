"use client";

import { useEffect, useRef, useState } from "react";

const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);

/**
 * Counts a figure up from zero when it first appears or changes. The final frame is always the
 * exact value from the API (same text and decimals), so animation never alters a reported number.
 * Non-numeric values ("not measured", "—") are shown as they are.
 */
export function CountUp({ value, duration = 900 }: { value: string | number; duration?: number }) {
  const text = String(value);
  const numeric = /^-?\d+(\.\d+)?$/.test(text.replace(/,/g, ""));
  const target = numeric ? Number(text.replace(/,/g, "")) : 0;
  const decimals = numeric && text.includes(".") ? text.split(".")[1].length : 0;
  const [shown, setShown] = useState(numeric ? (0).toFixed(decimals) : text);
  const from = useRef(0);

  useEffect(() => {
    if (!numeric) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const t = reduce ? 1 : Math.min(1, (now - start) / duration);
      const v = a + (target - a) * easeOut(t);
      setShown(t >= 1 ? text : v.toFixed(decimals));
      if (t < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [numeric, target, decimals, duration, text]);

  return <>{numeric ? shown : text}</>;
}
