import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Ban, ListTree, Play, ScrollText } from "lucide-react";
import toast from "react-hot-toast";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Icon } from "@/components/ui/Icon";
import { MetricRow } from "@/components/ui/MetricRow";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import {
  ACTIVE_MIGRATION_STATUSES,
  cancelMigration,
  getMigration,
  startMigration,
  type Migration,
} from "@/api/migrations";
import type { Vm } from "@/api/vms";
import { formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import type { ApiError } from "@/api/types";
import { STATUS_VARIANT, formatDuration } from "./Migrations";

const PIPELINE_STEPS = [
  { key: "validating", label: "validate" },
  { key: "preparing", label: "convert" },
  { key: "transferring", label: "transfer" },
  { key: "configuring", label: "adapt" },
  { key: "starting", label: "boot" },
  { key: "verifying", label: "verify" },
] as const;

const TERMINAL_OK = new Set(["completed"]);
const TERMINAL_KO = new Set(["failed", "cancelled", "rolled_back"]);

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

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

  const detailQuery = useQuery({
    queryKey: ["migration", id],
    queryFn: () => getMigration(id!),
    enabled: open,
    // Mid-flight migrations refresh every 3s so the operator can watch
    // the pipeline advance. Terminal migrations are static — no polling.
    refetchInterval: (query) => {
      const m = query.state.data;
      if (!m) return 5_000;
      return ACTIVE_MIGRATION_STATUSES.has(m.status) ? 3_000 : false;
    },
  });

  const startMutation = useMutation({
    mutationFn: () => startMigration(id!),
    onSuccess: () => {
      toast.success("migration started");
      queryClient.invalidateQueries({ queryKey: ["migration", id] });
      queryClient.invalidateQueries({ queryKey: ["migrations"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "migrations"] });
    },
    onError: (err) => toast.error(describeError(err, "start failed")),
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelMigration(id!, "cancelled from console"),
    onSuccess: () => {
      toast.success("cancellation requested");
      queryClient.invalidateQueries({ queryKey: ["migration", id] });
      queryClient.invalidateQueries({ queryKey: ["migrations"] });
    },
    onError: (err) => toast.error(describeError(err, "cancel failed")),
  });

  const migration = detailQuery.data;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title={migration ? `migration #${migration.id}` : "migration"}
      footer={
        migration && (
          <>
            <Button variant="secondary" onClick={onClose}>
              close
            </Button>
            {canControl && migration.status === "pending" && (
              <Button
                variant="primary"
                uppercase
                loading={startMutation.isPending}
                onClick={() => startMutation.mutate()}
                leadingIcon={<Icon icon={Play} size={14} />}
              >
                start
              </Button>
            )}
            {canControl && migration.is_active && migration.status !== "pending" && (
              <Button
                variant="secondary"
                uppercase
                loading={cancelMutation.isPending}
                onClick={() => {
                  if (window.confirm(`cancel migration #${migration.id}? this cannot be undone.`)) {
                    cancelMutation.mutate();
                  }
                }}
                leadingIcon={<Icon icon={Ban} size={14} />}
              >
                cancel
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
          {migration.error_message && (
            <Callout tone="err" kicker={migration.error_code ?? "error"}>
              <span className="break-words">{migration.error_message}</span>
            </Callout>
          )}
        </div>
      )}
    </SlideOver>
  );
}

function Hero({ migration, vms }: { migration: Migration; vms: Vm[] }) {
  const vm = vms.find((v) => v.id === migration.vm_id);
  const variant = STATUS_VARIANT[migration.status];
  const tone =
    TERMINAL_OK.has(migration.status)
      ? "ok"
      : TERMINAL_KO.has(migration.status)
        ? "white"
        : "signal";
  return (
    <section className="border border-line bg-bg-elev p-5">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Badge variant={variant}>{migration.status.replace(/_/g, " ")}</Badge>
        <span className="kicker">strategy · {migration.strategy}</span>
        {migration.requires_conversion && (
          <span className="kicker">conversion · {migration.conversion_format ?? "qcow2"}</span>
        )}
      </div>
      <div className="font-mono text-[14px] text-ink mb-1">
        {vm?.name ?? `vm#${migration.vm_id}`}
        <span className="ml-2 font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
          → {migration.target_namespace}
        </span>
      </div>
      <div className="mt-3">
        <ProgressBar
          value={migration.progress_percentage}
          variant={tone === "white" ? "white" : tone === "ok" ? "ok" : "signal"}
          showPct
        />
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
        <span>
          step {migration.current_step_number} / {migration.total_steps}
          {migration.current_step ? ` · ${migration.current_step}` : ""}
        </span>
        {migration.is_active && migration.estimated_time_remaining_seconds > 0 && (
          <span>eta · {formatDuration(migration.estimated_time_remaining_seconds)}</span>
        )}
      </div>
    </section>
  );
}

function Pipeline({ migration }: { migration: Migration }) {
  // Each pipeline cell reflects the status semantics:
  //   - "done" once the migration has advanced past it,
  //   - "active" when it matches the current status,
  //   - "failed" on the step that broke (best-effort from current_step_number),
  //   - "pending" otherwise.
  const currentIdx = PIPELINE_STEPS.findIndex((s) => s.key === migration.status);
  const completed = migration.status === "completed";
  const failed = migration.status === "failed";

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <Icon icon={ListTree} size={14} className="text-ink-muted" />
        <span className="kicker">pipeline</span>
      </div>
      <ol className="grid grid-cols-3 gap-2">
        {PIPELINE_STEPS.map((step, idx) => {
          let state: "done" | "active" | "failed" | "pending";
          if (completed) {
            state = "done";
          } else if (failed && idx === Math.max(0, migration.current_step_number - 1)) {
            state = "failed";
          } else if (currentIdx === idx) {
            state = "active";
          } else if (currentIdx > idx) {
            state = "done";
          } else {
            state = "pending";
          }
          return <PipelineCell key={step.key} index={idx + 1} label={step.label} state={state} />;
        })}
      </ol>
    </section>
  );
}

function PipelineCell({
  index,
  label,
  state,
}: {
  index: number;
  label: string;
  state: "done" | "active" | "failed" | "pending";
}) {
  const color =
    state === "done"
      ? "var(--ok)"
      : state === "active"
        ? "var(--signal)"
        : state === "failed"
          ? "var(--err)"
          : "var(--ink-faint)";
  return (
    <li
      className="border bg-bg-elev px-3 py-2"
      style={{
        borderColor: state === "pending" ? "var(--line)" : color,
        boxShadow:
          state === "active"
            ? `inset 0 0 0 1px color-mix(in srgb, ${color} 60%, transparent)`
            : undefined,
      }}
    >
      <div
        className="font-mono text-[10px] uppercase tracking-[0.06em]"
        style={{ color: state === "pending" ? "var(--ink-faint)" : color }}
      >
        {String(index).padStart(2, "0")} · {label}
      </div>
      <div
        className="font-mono text-[10px] uppercase tracking-[0.05em] mt-0.5"
        style={{ color: state === "pending" ? "var(--ink-faint)" : color }}
      >
        {state}
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
    { label: "namespace", value: migration.target_namespace },
    { label: "storage class", value: migration.target_storage_class },
    { label: "target node", value: migration.target_node ?? "—" },
    { label: "target vm name", value: migration.target_vm_name ?? "—" },
    { label: "transferred", value: transferred },
    { label: "source size", value: sourceSize },
    { label: "transfer rate", value: rate },
    { label: "duration", value: formatDuration(migration.duration_seconds) },
    { label: "scheduled", value: formatRelativeTime(migration.scheduled_at) },
    { label: "started", value: formatRelativeTime(migration.started_at) },
    { label: "completed", value: formatRelativeTime(migration.completed_at) },
  ];
  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <Icon icon={ScrollText} size={14} className="text-ink-muted" />
        <span className="kicker">facts</span>
      </div>
      <div>
        {rows.map((r) => (
          <MetricRow key={r.label} label={r.label} value={r.value} />
        ))}
      </div>
      {migration.notes && (
        <div className="mt-4 border border-line bg-bg-elev p-3">
          <div className="kicker mb-1.5">notes</div>
          <div className="font-mono text-[12px] text-ink whitespace-pre-wrap break-words">
            {migration.notes}
          </div>
        </div>
      )}
    </section>
  );
}
