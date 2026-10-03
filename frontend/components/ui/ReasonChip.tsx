import { reason } from "@/lib/labels";
import type { Tone } from "@/lib/format";
import { Badge } from "./primitives";
import { Tooltip } from "./Tooltip";

/** A reason code as a chip, with the code and a plain sentence on hover (rule 4: explain every decision). */
export function ReasonChip({ code, count, tone = "grey" }: { code: string; count?: number; tone?: Tone }) {
  const r = reason(code);
  return (
    <Tooltip
      content={
        <>
          <div className="font-mono text-[11px] text-white/70">{code}</div>
          <div className="mt-0.5">{r.sentence}</div>
          {count !== undefined && <div className="mt-1 text-white/70">Blocked {count} aircraft option{count === 1 ? "" : "s"}.</div>}
        </>
      }
    >
      <span tabIndex={0} className="cursor-help rounded-full focus-visible:outline-none focus-visible:shadow-focus">
        <Badge tone={tone}>
          {r.label}
          {count !== undefined && <span className="ml-0.5 opacity-70">× {count}</span>}
        </Badge>
      </span>
    </Tooltip>
  );
}
