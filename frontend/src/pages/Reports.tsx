import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  Clock,
  Download,
  FileBarChart,
  Gauge,
  HardDrive,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Panel } from "@/components/ui/Panel";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { StackedBar } from "@/components/ui/StackedBar";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { downloadCsv, rowsToCsv, type CsvColumn } from "@/lib/csv";
import {
  MIGRATION_STATUSES,
  listMigrations,
  type Migration,
  type MigrationStatus,
} from "@/api/migrations";
import { listVms, type Vm } from "@/api/vms";
import { fetchMigrationStats, type MigrationStats } from "@/api/stats";

const REPORT_PAGE_SIZE = 100;
const REFETCH_MS = 60_000;

const STATUS_VARIANT: Record<MigrationStatus, BadgeVariant> = {
  pending: "neutral",
  validating: "info",
  preparing: "info",
  transferring: "info",
  configuring: "info",
  starting: "info",
  verifying: "info",
  completed: "ok",
  failed: "critical",
  cancelled: "neutral",
  rollback: "warn",
  rolled_back: "warn",
};

function formatDuration(seconds: number): string {
  if (!seconds || seconds < 0) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function formatGB(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1) return `${value.toFixed(1)} GB`;
  return `${(value * 1024).toFixed(0)} MB`;
}

export default function Reports() {
  const statsQuery = useQuery<MigrationStats>({
    queryKey: ["stats", "migrations"],
    queryFn: fetchMigrationStats,
    refetchInterval: REFETCH_MS,
  });

  // The report set: most recent N migrations (any status). We pull a page
  // worth — anything beyond that belongs in a paginated export, not an
  // operator's dashboard.
  const recentQuery = useQuery({
    queryKey: ["migrations", "report"],
    queryFn: () => listMigrations({ skip: 0, limit: REPORT_PAGE_SIZE }),
    refetchInterval: REFETCH_MS,
  });

  // Light VM lookup — only the VMs referenced by the report rows show up.
  const vmsQuery = useQuery({
    queryKey: ["vms", "report-lookup"],
    queryFn: () => listVms({ skip: 0, limit: 200 }),
    staleTime: 5 * 60_000,
  });

  const items = recentQuery.data?.items ?? [];
  const vms = vmsQuery.data?.items ?? [];

  const breakdown = useMemo(() => computeBreakdown(items), [items]);
  const csv = useMemo(() => makeCsv(items, vms), [items, vms]);

  return (
    <div className="max-w-[1440px] mx-auto p-6 md:p-8 space-y-6">
      <PageHeader
        kicker="operations"
        title="reports"
        breadcrumbs={[{ label: "console" }, { label: "operations" }, { label: "reports" }]}
        description="Historical migration outcomes for audit, SLA review, and capacity planning."
        actions={
          <Button
            variant="primary"
            uppercase
            leadingIcon={<Icon icon={Download} size={14} />}
            disabled={items.length === 0}
            onClick={() => downloadCsv(buildFilename(), csv)}
          >
            export csv
          </Button>
        }
      />

      <StatsStrip stats={statsQuery.data} isLoading={statsQuery.isPending} />

      <BreakdownPanel breakdown={breakdown} total={items.length} isLoading={recentQuery.isPending} />

      <Panel
        density="compact"
        kicker={`${items.length} migrations · last ${REPORT_PAGE_SIZE} max`}
        title="migration history"
        bodyClassName="px-0"
      >
        <HistoryTable
          items={items}
          vms={vms}
          isLoading={recentQuery.isPending}
          isError={recentQuery.isError}
        />
      </Panel>

      <Callout tone="info">
        the export bundles only the rows currently loaded · for full
        history use the backend API directly or wait for the scheduled
        export job (roadmap).
      </Callout>
    </div>
  );
}

/* ------------------------------- stats strip ------------------------------ */

function StatsStrip({
  stats,
  isLoading,
}: {
  stats: MigrationStats | undefined;
  isLoading: boolean;
}) {
  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <Tile
        kicker="success rate"
        value={isLoading ? null : `${(stats?.success_rate ?? 0).toFixed(0)}%`}
        tone="ok"
        icon={Gauge}
      />
      <Tile
        kicker="completed"
        value={isLoading ? null : formatNumber(stats?.completed)}
        suffix={stats ? `/ ${formatNumber(stats.total_migrations)}` : undefined}
        tone="ok"
        icon={CheckCircle2}
      />
      <Tile
        kicker="failed"
        value={isLoading ? null : formatNumber(stats?.failed)}
        tone="err"
        icon={XCircle}
      />
      <Tile
        kicker="data transferred"
        value={isLoading ? null : formatGB(stats?.total_data_transferred_gb)}
        hint={
          stats?.average_duration_seconds
            ? `avg run · ${formatDuration(stats.average_duration_seconds)}`
            : undefined
        }
        tone="signal"
        icon={HardDrive}
      />
    </section>
  );
}

function Tile({
  kicker,
  value,
  suffix,
  hint,
  tone,
  icon,
}: {
  kicker: string;
  value: string | null;
  suffix?: string;
  hint?: string;
  tone: "ok" | "err" | "muted" | "signal";
  icon?: typeof FileBarChart;
}) {
  const color =
    tone === "ok"
      ? "var(--ok)"
      : tone === "err"
        ? "var(--err)"
        : tone === "signal"
          ? "var(--signal)"
          : "var(--ink)";
  return (
    <Panel density="compact">
      <div className="flex items-start justify-between gap-3">
        <span className="kicker">{kicker}</span>
        {icon && <Icon icon={icon} size={14} className="text-ink-faint" />}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        {value === null ? (
          <Skeleton className="h-7 w-20" />
        ) : (
          <span className="font-mono tabular text-[28px] leading-none" style={{ color }}>
            {value}
          </span>
        )}
        {suffix && <span className="font-mono text-[12px] text-ink-muted">{suffix}</span>}
      </div>
      {hint && (
        <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint truncate">
          {hint}
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------ breakdown --------------------------------- */

type Breakdown = Record<MigrationStatus, number>;

function computeBreakdown(items: Migration[]): Breakdown {
  const out = Object.fromEntries(MIGRATION_STATUSES.map((s) => [s, 0])) as Breakdown;
  for (const m of items) out[m.status] += 1;
  return out;
}

function BreakdownPanel({
  breakdown,
  total,
  isLoading,
}: {
  breakdown: Breakdown;
  total: number;
  isLoading: boolean;
}) {
  const completed = breakdown.completed;
  const failed = breakdown.failed + breakdown.rolled_back;
  const active =
    breakdown.validating +
    breakdown.preparing +
    breakdown.transferring +
    breakdown.configuring +
    breakdown.starting +
    breakdown.verifying +
    breakdown.rollback;
  const idle = breakdown.pending + breakdown.cancelled;

  const segments = [
    { key: "ok", label: "completed", value: completed, color: "var(--ok)" },
    { key: "active", label: "in progress", value: active, color: "var(--signal)" },
    { key: "failed", label: "failed", value: failed, color: "var(--err)" },
    { key: "idle", label: "pending / cancelled", value: idle, color: "var(--ink-faint)" },
  ];

  return (
    <Panel
      density="compact"
      kicker={`status mix · last ${total} rows`}
      title="outcome distribution"
      action={
        <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
          {total > 0 ? `${((completed / total) * 100).toFixed(0)}% completed in window` : "no data"}
        </span>
      }
    >
      {isLoading ? (
        <Skeleton className="h-14 w-full" />
      ) : total === 0 ? (
        <div className="font-mono text-[11px] text-ink-muted uppercase tracking-[0.05em]">
          no migrations yet · trigger one from the migrations page
        </div>
      ) : (
        <StackedBar segments={segments} height={12} />
      )}
    </Panel>
  );
}

/* -------------------------------- history --------------------------------- */

function vmName(id: number, vms: Vm[]): string {
  return vms.find((v) => v.id === id)?.name ?? `vm#${id}`;
}

function HistoryTable({
  items,
  vms,
  isLoading,
  isError,
}: {
  items: Migration[];
  vms: Vm[];
  isLoading: boolean;
  isError: boolean;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          failed to load migration history.
        </Callout>
      </div>
    );
  }

  if (isLoading && items.length === 0) {
    return (
      <div className="px-6 pb-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonRow key={i} cols={6} />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={FileBarChart}
        title="no migrations"
        hint="reports populate after the first migration completes."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table className="border-0">
        <THead>
          <TR>
            <TH>#</TH>
            <TH>vm</TH>
            <TH>strategy</TH>
            <TH>status</TH>
            <TH numeric>transferred</TH>
            <TH numeric>duration</TH>
            <TH numeric>completed</TH>
          </TR>
        </THead>
        <tbody>
          {items.map((m, i) => (
            <TR key={m.id} className="sw-mount">
              <TD mono muted style={{ "--sw-i": i } as React.CSSProperties}>
                #{m.id}
              </TD>
              <TD>{vmName(m.vm_id, vms)}</TD>
              <TD mono muted>{m.strategy}</TD>
              <TD>
                <Badge variant={STATUS_VARIANT[m.status]}>{m.status.replace(/_/g, " ")}</Badge>
              </TD>
              <TD numeric muted>{formatGB(m.transferred_gb || null)}</TD>
              <TD numeric muted>{formatDuration(m.duration_seconds)}</TD>
              <TD numeric muted>
                {m.completed_at ? (
                  formatRelativeTime(m.completed_at)
                ) : (
                  <span className="inline-flex items-center gap-1 text-ink-faint">
                    <Icon icon={Clock} size={11} />
                    n/a
                  </span>
                )}
              </TD>
            </TR>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

/* ----------------------------------- csv ---------------------------------- */

function makeCsv(items: Migration[], vms: Vm[]): string {
  const columns: CsvColumn<Migration>[] = [
    { header: "id", value: (m) => m.id },
    { header: "vm_id", value: (m) => m.vm_id },
    { header: "vm_name", value: (m) => vmName(m.vm_id, vms) },
    { header: "status", value: (m) => m.status },
    { header: "strategy", value: (m) => m.strategy },
    { header: "target_namespace", value: (m) => m.target_namespace },
    { header: "target_storage_class", value: (m) => m.target_storage_class },
    { header: "progress_percentage", value: (m) => m.progress_percentage.toFixed(1) },
    { header: "transferred_gb", value: (m) => m.transferred_gb.toFixed(2) },
    {
      header: "source_size_gb",
      value: (m) => (m.source_size_gb == null ? "" : m.source_size_gb.toFixed(2)),
    },
    { header: "duration_seconds", value: (m) => m.duration_seconds },
    { header: "success", value: (m) => (m.success == null ? "" : String(m.success)) },
    { header: "error_code", value: (m) => m.error_code ?? "" },
    { header: "error_message", value: (m) => m.error_message ?? "" },
    { header: "created_at", value: (m) => m.created_at },
    { header: "started_at", value: (m) => m.started_at ?? "" },
    { header: "completed_at", value: (m) => m.completed_at ?? "" },
  ];
  return rowsToCsv(items, columns);
}

function buildFilename(): string {
  const now = new Date();
  const stamp = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  return `shiftwise-migrations-${stamp}.csv`;
}
