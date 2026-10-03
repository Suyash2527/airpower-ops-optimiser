"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  ["/", "Scenario"],
  ["/map", "Map"],
  ["/plan", "Plan"],
  ["/timeline", "Timeline"],
  ["/resources", "Fleet & crew"],
  ["/proposals", "Proposals"],
  ["/audit", "Audit"],
] as const;

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="flex flex-wrap gap-1 text-sm">
      {LINKS.map(([href, label]) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 font-medium ${active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"}`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
