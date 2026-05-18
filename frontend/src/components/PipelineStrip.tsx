import { Check, ChevronRight, CircleDashed, Loader2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Fragment } from "react";
import { cn } from "@/lib/cn";

export type PipelineStageState = "done" | "active" | "pending";

/**
 * Per-state cue rendered alongside the stage label. Status is otherwise
 * encoded only by background colour — this icon + word pair makes each
 * state legible without relying on colour perception (WCAG 1.4.1).
 */
const STAGE_STATE_META: Record<
  PipelineStageState,
  { icon: LucideIcon; word: string; spin?: boolean }
> = {
  done: { icon: Check, word: "Done" },
  active: { icon: Loader2, word: "Running", spin: true },
  pending: { icon: CircleDashed, word: "Pending" },
};

export type PipelineStageData = {
  key: string;
  label: string;
  icon: LucideIcon;
  count: number | string;
  meta?: string;
  /** 0–100 progress for this stage. Optional — omit to hide the bar. */
  progress?: number;
  state: PipelineStageState;
};

/**
 * Migration pipeline stage strip.
 * Five tiles in a row, each with an icon, name, count, meta line, and progress bar.
 * Connected by ChevronRight glyphs between tiles.
 */
export function PipelineStrip({ stages }: { stages: PipelineStageData[] }) {
  return (
    <div
      className="grid items-stretch gap-1"
      style={{
        gridTemplateColumns: `repeat(${stages.length}, 1fr) auto`,
      }}
    >
      {stages.map((stage, i) => (
        <Fragment key={stage.key}>
          <Stage stage={stage} />
          {i < stages.length - 1 && (
            <span className="grid place-items-center text-[var(--text-muted)] px-1">
              <ChevronRight size={14} strokeWidth={2} />
            </span>
          )}
        </Fragment>
      ))}
    </div>
  );
}

function Stage({ stage }: { stage: PipelineStageData }) {
  const { state, icon: IconComponent, label, count, meta, progress } = stage;
  const stageBg =
    state === "active"
      ? "linear-gradient(135deg, rgba(230, 38, 0, 0.16), rgba(255, 122, 47, 0.08))"
      : state === "done"
        ? "linear-gradient(135deg, rgba(1, 181, 116, 0.12), rgba(46, 204, 138, 0.04))"
        : "transparent";
  const stageShadow =
    state === "active"
      ? "0 0 0 1px rgba(230, 38, 0, 0.3), 0 8px 24px -8px rgba(230, 38, 0, 0.35)"
      : "none";

  const iconClass =
    state === "active"
      ? "icon-container icon-container--accent"
      : state === "done"
        ? "icon-container icon-container--success"
        : "icon-container icon-container--muted";

  const progressFill =
    state === "done"
      ? "linear-gradient(90deg, var(--alert-success), var(--alert-success-light))"
      : "linear-gradient(90deg, var(--accent-primary), var(--accent-light))";

  const stateMeta = STAGE_STATE_META[state];
  const stateColor =
    state === "done"
      ? "var(--alert-success-light)"
      : state === "active"
        ? "var(--accent-light)"
        : "var(--text-muted)";
  const StateIcon = stateMeta.icon;

  return (
    <div
      className={cn("relative p-4 rounded-2xl transition-all duration-200")}
      style={{ background: stageBg, boxShadow: stageShadow }}
    >
      <div className="flex items-center gap-2.5 mb-2">
        <span className={cn(iconClass, "w-8 h-8 rounded-[9px]")}>
          <IconComponent size={16} strokeWidth={1.75} />
        </span>
        <span className="text-[12px] font-bold text-[var(--text-primary)]">
          {label}
        </span>
      </div>
      {/* Non-colour state cue — icon + word — so the stage status is
          legible without relying on the background colour alone. */}
      <div
        className="flex items-center gap-1 mb-2 text-[10px] font-bold uppercase tracking-[0.04em]"
        style={{ color: stateColor }}
      >
        <StateIcon
          size={11}
          strokeWidth={2.25}
          className={stateMeta.spin ? "sw-spin" : undefined}
          aria-hidden
        />
        <span>{stateMeta.word}</span>
      </div>
      <div
        className={cn(
          "text-[22px] font-bold tabular leading-none tracking-[-0.02em]",
          state === "pending"
            ? "text-[var(--text-muted)]"
            : "text-[var(--text-primary)]",
        )}
      >
        {count}
      </div>
      {meta && (
        <div className="text-[11px] text-[var(--text-secondary)] mt-1">{meta}</div>
      )}
      {progress !== undefined && (
        <div
          className="mt-2.5 h-1 rounded-full overflow-hidden"
          style={{ background: "var(--surface-soft-strong)" }}
        >
          <div
            className="h-full rounded-full transition-[width] duration-[var(--dur-slow)]"
            style={{
              width: `${Math.max(0, Math.min(100, progress))}%`,
              background: progressFill,
            }}
          />
        </div>
      )}
    </div>
  );
}
