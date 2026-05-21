import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRightLeft,
  CheckCircle2,
  Download,
  FileBarChart,
  Gauge,
  HardDrive,
  XCircle,
} from "lucide-react";
import { MigrationStatusBadge, type MigrationStatusKey } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Panel } from "@/components/ui/Panel";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { StackedBar } from "@/components/ui/StackedBar";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import {
  formatDuration,
  formatGB,
  formatNumber,
  formatRelativeTime,
} from "@/lib/format";
import { downloadCsv, rowsToCsv, type CsvColumn } from "@/lib/csv";
import {
  MIGRATION_STATUSES,
  listMigrations,
  type Migration,
  type MigrationStatus,
} from "@/api/migrations";
import { listVms, type Vm } from "@/api/vms";
import { fetchMigrationStats, type MigrationStats } from "@/api/stats";
import { PerHypervisorPanel } from "@/pages/PerHypervisorPanel";
import { PerTenantPanel } from "@/pages/PerTenantPanel";

const REPORT_PAGE_SIZE = 100;
const REFETCH_MS = 60_000;

export default function Reports() {
  const statsQuery = useQuery<MigrationStats>({
    queryKey: ["stats", "migrations"],
    queryFn: fetchMigrationStats,
    refetchInterval: REFETCH_MS,
  });

  const recentQuery = useQuery({
    queryKey: ["migrations", "report"],
    queryFn: () => listMigrations({ skip: 0, limit: REPORT_PAGE_SIZE }),
    refetchInterval: REFETCH_MS,
  });

  const vmsQuery = useQuery({
    queryKey: ["vms", "report-lookup"],
    queryFn: () => listVms({ skip: 0, limit: 100 }),
    staleTime: 5 * 60_000,
  });

  const items = recentQuery.data?.items ?? [];
  const vms = vmsQuery.data?.items ?? [];

  const breakdown = useMemo(() => computeBreakdown(items), [items]);
  const csv = useMemo(() => makeCsv(items, vms), [items, vms]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Reports"
        description="Historical migration outcomes for audit, SLA review, and capacity planning."
        actions={
          <Button
            variant="primary"
            leadingIcon={<Icon icon={Download} size={14} strokeWidth={2.25} />}
            disabled={items.length === 0}
            onClick={() => downloadCsv(buildFilename(), csv)}
          >
            Export CSV
          </Button>
        }
      />

      <StatsStrip
        stats={statsQuery.data}
        isLoading={statsQuery.isPending}
        isError={statsQuery.isError}
      />

      <BreakdownPanel
        breakdown={breakdown}
        total={items.length}
        isLoading={recentQuery.isPending}
      />

      <PerHypervisorPanel rows={statsQuery.data?.by_hypervisor ?? []} />

      <PerTenantPanel rows={statsQuery.data?.by_tenant ?? []} />

      <Panel
        kicker={`${items.length} migrations · last ${REPORT_PAGE_SIZE} max`}
        title="Migration History"
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
        The export includes only the rows currently loaded. For full history, use the backend API directly or wait for the scheduled export job (roadmap).
      </Callout>
    </div>
  );
}

/* ------------------------------- stats strip ------------------------------ */

function StatsStrip({
  stats,
  isLoading,
  isError,
}: {
  stats: MigrationStats | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  if (isError) {
    return (
      <Callout tone="err" role="alert">
        Could not load migration stats. Refresh to retry.
      </Callout>
    );
  }
  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-6">
      <KPIPrimary
        label="Success Rate"
        value={
          isLoading ? <Skeleton className="h-5 w-12" /> : `${(stats?.success_rate ?? 0).toFixed(0)}%`
        }
        icon={Gauge}
        iconTone="success"
      />
      <KPIPrimary
        label="Completed"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(stats?.completed)}
        delta={stats ? `/ ${formatNumber(stats.total_migrations)}` : undefined}
        deltaTone="neutral"
        icon={CheckCircle2}
        iconTone="success"
      />
      <KPIPrimary
        label="Failed"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(stats?.failed)}
        icon={XCircle}
        iconTone="warn"
      />
      <KPIPrimary
        label="Data Transferred"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatGB(stats?.total_data_transferred_gb)}
        delta={
          stats?.average_duration_seconds
            ? `Avg ${formatDuration(stats.average_duration_seconds)}`
            : undefined
        }
        deltaTone="neutral"
        icon={HardDrive}
        iconTone="accent"
      />
    </section>
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
    { key: "ok",     label: "Completed",         value: completed, color: "var(--alert-success)" },
    { key: "active", label: "In progress",       value: active,    color: "var(--accent-primary)" },
    { key: "failed", label: "Failed",            value: failed,    color: "var(--alert-critical)" },
    { key: "idle",   label: "Pending / cancelled", value: idle,    color: "var(--text-muted)" },
  ];

  return (
    <Panel
      icon={Activity}
      iconTone="accent"
      kicker={`Status mix · last ${total} rows`}
      title="Outcome Distribution"
      action={
        <span className="text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
          {total > 0 ? `${((completed / total) * 100).toFixed(0)}% completed in window` : "No data"}
        </span>
      }
    >
      {isLoading ? (
        <Skeleton className="h-14 w-full" />
      ) : total === 0 ? (
        <div className="text-[12px] text-[var(--text-secondary)]">
          No migrations yet. Trigger one from the Migrations page.
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
  const navigate = useNavigate();

  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          Could not load migration history. Refresh to retry.
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
        title="No history to report"
        hint="Once migrations complete, this page tracks their outcomes, transfer volumes, and durations for audit and capacity planning. Run the first migration to populate it."
        action={
          <Button
            variant="primary"
            leadingIcon={<Icon icon={ArrowRightLeft} size={14} strokeWidth={2.25} />}
            onClick={() => navigate("/migrations")}
          >
            Go to Migrations
          </Button>
        }
      />
    );
  }

  return (
    <Table className="px-2">
      <THead>
        <TR>
          <TH>#</TH>
          <TH>VM</TH>
          <TH>Strategy</TH>
          <TH>Status</TH>
          <TH numeric>Transferred</TH>
          <TH numeric>Duration</TH>
          <TH numeric>Completed</TH>
        </TR>
      </THead>
      <tbody>
        {items.map((m) => (
          <TR key={m.id}>
            <TD muted>
              <span className="tabular font-bold text-[var(--text-primary)]">#{m.id}</span>
            </TD>
            <TD>{vmName(m.vm_id, vms)}</TD>
            <TD muted>{m.strategy}</TD>
            <TD>
              <MigrationStatusBadge status={m.status.toUpperCase() as MigrationStatusKey} />
            </TD>
            <TD numeric muted>
              {formatGB(m.transferred_gb || null)}
            </TD>
            <TD numeric muted>
              {formatDuration(m.duration_seconds)}
            </TD>
            <TD numeric muted>
              {m.completed_at ? formatRelativeTime(m.completed_at) : "—"}
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
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
