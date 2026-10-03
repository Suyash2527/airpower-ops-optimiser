"use client";

import { useSyncExternalStore } from "react";

// Count of actions in flight anywhere in the app; drives the top progress bar.
let count = 0;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

export const busyStart = () => {
  count += 1;
  emit();
};
export const busyEnd = () => {
  count = Math.max(0, count - 1);
  emit();
};

export const useBusy = () =>
  useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => {
        subs.delete(f);
      };
    },
    () => count > 0,
    () => false,
  );
