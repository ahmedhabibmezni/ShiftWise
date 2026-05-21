import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Check,
  CircleDashed,
  ListTree,
  Loader2,
  Play,
  ScrollText,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import toast from "react-hot-toast";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Icon } from "@/components/ui/Icon";
import { MetricRow } from "@/components/ui/MetricRow";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import {
  MigrationStatusBadge,
  type MigrationStatusKey,
} from "@/components/ui/StatusBadge";
import {
  ACTIVE_MIGRATION_STATUSES,
  cancelMigration,
  getMigration,
  startMigration,
  type Migration,
} from "@/api/migrations";
import type { Vm } from "@/api/vms";
import { formatDuration, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { describeError } from "@/lib/errors";
import { MigrationTimeline } from "@/pages/MigrationTimeline";

const PIPELINE_STEPS = [
  { key: "validating",  label: "Validate" },
  { key: "preparing",   label: "Convert" },
  { key: "transferring", label: "Transfer" },
  { key: "configuring", label: "Adapt" },
  { key: "starting",    label: "Boot" },
  { key: "verifying",   label: "Verify" },
] as const;

const TERMINAL_OK = new Set(["completed"]);
const TERMINAL_KO = new Set(["failed", "cancelled", "rolled_back"]);

export function MigrationDetailDrawer({
  id,
  onClose,
  vms,
}: {
  id: number | null;
  onClose: () => void;
  vms: Vm[];
}) {
  const queryClient = useQueryClient();
  const open = id !== null;
  const canControl = useHasPermission("migrations", "update");
  // The parent remounts this drawer via a `key` per selected id, so
  // `confirmCancel` starts false on every open — no reset effect needed.
  const [confirmCancel, setConfirmCancel] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["migration", id],
    queryFn: () => getMigration(id!),
    enabled: open,
    refetchInterval: (query) => {
      const m = query.state.data;
      if (!m) return 5_000;
      return ACTIVE_MIGRATION_STATUSES.has(m.status) ? 3_000 : false;
    },
  });

  const startMutation = useMutation({
    mutationFn: () => startMigration(id!),
    onSuccess: () => {
      toast.success("Migration started");
      queryClient.invalidateQueries({ queryKey: ["migration", id] });
      queryClient.invalidateQueries({ queryKey: ["migrations"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "migrations"] });
    },
    onError: (err) => toast.error(describeError(err, "Start failed")),
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelMigration(id!, "Cancelled from console"),
    onSuccess: () => {
      toast.success("Cancellation requested");
      setConfirmCancel(false);
      queryClient.invalidateQueries({ queryKey: ["migration", id] });
      queryClient.invalidateQueries({ queryKey: ["migrations"] });
    },
    onError: (err) => {
      setConfirmCancel(false);
      toast.error(describeError(err, "Cancel failed"));
    },
  });

  const migration = detailQuery.data;
  const migrationVm = migration
    ? vms.find((v) => v.id === migration.vm_id)
    : undefined;

  return (
    <>
    <SlideOver
      open={open}
      onClose={onClose}
      title={migration ? `Migration #${migration.id}` : "Migration"}
      footer={
        migration && (
          <>
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
            {canControl && migration.status === "pending" && (
              <Button
                variant="primary"
                loading={startMutation.isPending}
                onClick={() => startMutation.mutate()}
                leadingIcon={<Icon icon={Play} size={14} />}
              >
                Start
              </Button>
            )}
            {canControl && migration.is_active && migration.status !== "pending" && (
              <Button
                variant="secondary"
                loading={cancelMutation.isPending}
                onClick={() => setConfirmCancel(true)}
                leadingIcon={<Icon icon={Ban} size={14} />}
              >
                Cancel
              </Button>
            )}
          </>
        )
      }
    >
      {!migration ? (
        <div className="space-y-3">
          <Skeleton className="h-7 w-44" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="space-y-6">
          <Hero migration={migration} vms={vms} />
          <Pipeline migration={migration} />
          <Facts migration={migration} />
          <MigrationTimeline
            migrationId={migration.id}
            status={migration.status}
          />
          {migration.error_message && (
            <Callout tone="err" kicker={migration.error_code ?? "Error"}>
              <span className="break-words">{migration.error_message}</span>
            </Callout>
          )}
        </div>
      )}
    </SlideOver>
    {migration && (
      <ConfirmDialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        onConfirm={() => cancelMutation.mutate()}
        loading={cancelMutation.isPending}
        icon={Ban}
        title="Cancel this migration?"
        confirmLabel="Cancel migration"
        cancelLabel="Keep running"
        message={
          <>
            Migration #{migration.id} of{" "}
            <strong className="font-bold text-[var(--text-primary)]">
              {migrationVm?.name ?? `vm#${migration.vm_id}`}
            </strong>{" "}
            stops at the current step. Transferred disk data is discarded and
            the target VM is not created. The source VM stays untouched, so the
            migration can be started again later.
          </>
        }
      />
    )}
    </>
  );
}

function Hero({ migration, vms }: { migration: Migration; vms: Vm[] }) {
  const vm = vms.find((v) => v.id === migration.vm_id);
  const tone = TERMINAL_OK.has(migration.status)
    ? "ok"
    : TERMINAL_KO.has(migration.status)
      ? "err"
      : "signal";
  return (
    <section className="rounded-2xl bg-[var(--surface-soft)] p-5">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <MigrationStatusBadge status={migration.status.toUpperCase() as MigrationStatusKey} />
        <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-[0.04em]">
          Strategy · {migration.strategy}
        </span>
        {migration.requires_conversion && (
          <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-[0.04em]">
            Conversion · {migration.conversion_format ?? "qcow2"}
          </span>
        )}
      </div>
      <div className="text-[15px] font-bold text-[var(--text-primary)] mb-1">
        {vm?.name ?? `vm#${migration.vm_id}`}
        <span className="ml-2 text-[11px] uppercase tracking-[0.04em] font-bold text-[var(--text-secondary)]">
          → {migration.target_namespace}
        </span>
      </div>
      <div className="mt-3">
        <ProgressBar value={migration.progress_percentage} variant={tone} showPct />
      </div>
      <div className="mt-2 flex items-center justify-between text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
        <span>
          Step {migration.current_step_number} / {migration.total_steps}
          {migration.current_step ? ` · ${migration.current_step}` : ""}
        </span>
        {migration.is_active && migration.estimated_time_remaining_seconds > 0 && (
          <span>ETA · {formatDuration(migration.estimated_time_remaining_seconds)}</span>
        )}
      </div>
    </section>
  );
}

function Pipeline({ migration }: { migration: Migration }) {
  const currentIdx = PIPELINE_STEPS.findIndex((s) => s.key === migration.status);
  const completed = migration.status === "completed";
  const failed = migration.status === "failed";

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <Icon icon={ListTree} size={14} className="text-[var(--text-muted)]" />
        <span className="kicker">Pipeline</span>
      </div>
      <ol className="grid grid-cols-3 gap-2">
        {PIPELINE_STEPS.map((step, idx) => {
          let state: "done" | "active" | "failed" | "pending";
          if (completed) state = "done";
          else if (failed && idx === Math.max(0, migration.current_step_number - 1)) state = "failed";
          else if (currentIdx === idx) state = "active";
          else if (currentIdx > idx) state = "done";
          else state = "pending";
          return <PipelineCell key={step.key} index={idx + 1} label={step.label} state={state} />;
        })}
      </ol>
    </section>
  );
}

type PipelineCellState = "done" | "active" | "failed" | "pending";

/**
 * Per-state icon. The pipeline cell encodes status with a background colour;
 * pairing each state with a distinct glyph keeps it legible for colourblind
 * users (WCAG 1.4.1 — colour is not the only cue).
 */
const PIPELINE_CELL_ICON: Record<
  PipelineCellState,
  { icon: LucideIcon; spin?: boolean }
> = {
  done: { icon: Check },
  active: { icon: Loader2, spin: true },
  failed: { icon: X },
  pending: { icon: CircleDashed },
};

function PipelineCell({
  index,
  label,
  state,
}: {
  index: number;
  label: string;
  state: PipelineCellState;
}) {
  const tone =
    state === "done"
      ? { color: "var(--alert-success-light)", bg: "rgba(1, 181, 116, 0.10)" }
      : state === "active"
        ? { color: "var(--accent-light)", bg: "rgba(230, 38, 0, 0.12)" }
        : state === "failed"
          ? { color: "var(--alert-critical)", bg: "rgba(224, 61, 61, 0.10)" }
          : { color: "var(--text-muted)", bg: "var(--surface-soft)" };
  const StateIcon = PIPELINE_CELL_ICON[state].icon;
  return (
    <li className="rounded-xl px-3.5 py-2.5" style={{ background: tone.bg }}>
      <div
        className="text-[10px] uppercase tracking-[0.04em] font-bold"
        style={{ color: tone.color }}
      >
        {String(index).padStart(2, "0")} · {label}
      </div>
      <div
        className="flex items-center gap-1 text-[10px] uppercase tracking-[0.04em] font-medium mt-0.5"
        style={{ color: tone.color, opacity: 0.85 }}
      >
        <StateIcon
          size={10}
          strokeWidth={2.5}
          className={PIPELINE_CELL_ICON[state].spin ? "sw-spin" : undefined}
          aria-hidden
        />
        <span>{state}</span>
      </div>
    </li>
  );
}

function Facts({ migration }: { migration: Migration }) {
  const transferred = migration.transferred_gb > 0 ? `${migration.transferred_gb.toFixed(1)} GB` : "—";
  const sourceSize =
    migration.source_size_gb != null ? `${migration.source_size_gb.toFixed(1)} GB` : "—";
  const rate =
    migration.transfer_rate_mbps != null && migration.transfer_rate_mbps > 0
      ? `${migration.transfer_rate_mbps.toFixed(1)} Mbps`
      : "—";

  const rows: { label: string; value: string }[] = [
    { label: "Namespace", value: migration.target_namespace },
    { label: "Storage Class", value: migration.target_storage_class },
    { label: "Target Node", value: migration.target_node ?? "—" },
    { label: "Target VM Name", value: migration.target_vm_name ?? "—" },
    { label: "Transferred", value: transferred },
    { label: "Source Size", value: sourceSize },
    { label: "Transfer Rate", value: rate },
    { label: "Duration", value: formatDuration(migration.duration_seconds) },
    { label: "Scheduled", value: formatRelativeTime(migration.scheduled_at) },
    { label: "Started", value: formatRelativeTime(migration.started_at) },
    { label: "Completed", value: formatRelativeTime(migration.completed_at) },
  ];
  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <Icon icon={ScrollText} size={14} className="text-[var(--text-muted)]" />
        <span className="kicker">Facts</span>
      </div>
      <div>
        {rows.map((r) => (
          <MetricRow key={r.label} label={r.label} value={r.value} />
        ))}
      </div>
      {migration.notes && (
        <div className="mt-4 rounded-xl bg-[var(--surface-soft)] p-4">
          <div className="kicker mb-1.5">Notes</div>
          <div className="text-[13px] text-[var(--text-primary)] whitespace-pre-wrap break-words leading-relaxed">
            {migration.notes}
          </div>
        </div>
      )}
    </section>
  );
}
