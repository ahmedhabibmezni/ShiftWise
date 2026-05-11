import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Plus,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Select } from "@/components/ui/Select";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { Panel } from "@/components/ui/Panel";
import { PageHeader } from "@/components/ui/PageHeader";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Callout } from "@/components/ui/Callout";
import {
  ACTIVE_MIGRATION_STATUSES,
  MIGRATION_STATUSES,
  MIGRATION_STRATEGIES,
  listMigrations,
  type Migration,
  type MigrationStatus,
  type MigrationStrategy,
} from "@/api/migrations";
import { listVms, type Vm } from "@/api/vms";
import { fetchMigrationStats, type MigrationStats } from "@/api/stats";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { MigrationCreateDrawer } from "./MigrationCreateDrawer";
import { MigrationDetailDrawer } from "./MigrationDetailDrawer";

const PAGE_SIZE = 25;
const REFETCH_IDLE_MS = 30_000;
const REFETCH_ACTIVE_MS = 5_000;

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

export default function Migrations() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<MigrationStatus | "">("");
  const [strategyFilter, setStrategyFilter] = useState<MigrationStrategy | "">("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const canCreate = useHasPermission("migrations", "create");

  const params = useMemo(
    () => ({
      skip: (page - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(strategyFilter ? { strategy: strategyFilter } : {}),
    }),
    [page, statusFilter, strategyFilter],
  );

  const listQuery = useQuery({
    queryKey: ["migrations", params],
    queryFn: () => listMigrations(params),
    // Poll faster when any visible migration is mid-flight — gives the operator
    // a near-live view of progress without hammering when the table is idle.
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasActive = data?.items.some((m) => ACTIVE_MIGRATION_STATUSES.has(m.status));
      return hasActive ? REFETCH_ACTIVE_MS : REFETCH_IDLE_MS;
    },
    placeholderData: (prev) => prev,
  });

  const statsQuery = useQuery<MigrationStats>({
    queryKey: ["stats", "migrations"],
    queryFn: fetchMigrationStats,
    refetchInterval: REFETCH_IDLE_MS,
  });

  // Light VM list — used to display human-readable names in the table.
  // 100-item ceiling is intentional: this is a quick lookup, not a full sync.
  const vmsQuery = useQuery({
    queryKey: ["vms", "all-light"],
    queryFn: () => listVms({ skip: 0, limit: 100 }),
    staleTime: 5 * 60_000,
  });

  const totalPages = listQuery.data
    ? Math.max(1, Math.ceil(listQuery.data.total / PAGE_SIZE))
    : 1;
  const items = listQuery.data?.items ?? [];
  const filtersActive = !!(statusFilter || strategyFilter);

  return (
    <div className="max-w-[1440px] mx-auto p-6 md:p-8 space-y-6">
      <PageHeader
        kicker="operations"
        title="migrations"
        breadcrumbs={[{ label: "console" }, { label: "operations" }, { label: "migrations" }]}
        description="VM → KubeVirt pipeline. Discovery → Analyzer → Converter → Adapter → Migrator."
        actions={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={16} />}
              onClick={() => setCreateOpen(true)}
            >
              new migration
            </Button>
          ) : null
        }
      />

      <StatsStrip stats={statsQuery.data} isLoading={statsQuery.isPending} />

      <Panel
        density="compact"
        kicker={
          filtersActive
            ? `filters active · ${listQuery.data?.total ?? 0} results`
            : `${listQuery.data?.total ?? 0} migrations recorded`
        }
        title="pipeline log"
        action={
          <Toolbar
            statusFilter={statusFilter}
            onStatusFilter={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
            strategyFilter={strategyFilter}
            onStrategyFilter={(v) => {
              setStrategyFilter(v);
              setPage(1);
            }}
          />
        }
        bodyClassName="px-0"
      >
        <MigrationTable
          items={items}
          isLoading={listQuery.isPending}
          isError={listQuery.isError}
          onRowClick={(id) => setSelectedId(id)}
          vms={vmsQuery.data?.items ?? []}
          onCreate={() => setCreateOpen(true)}
          canCreate={canCreate}
        />
      </Panel>

      <Pagination
        page={page}
        totalPages={totalPages}
        total={listQuery.data?.total ?? 0}
        pageSize={PAGE_SIZE}
        onChange={setPage}
      />

      <MigrationDetailDrawer
        id={selectedId}
        onClose={() => setSelectedId(null)}
        vms={vmsQuery.data?.items ?? []}
      />
      <MigrationCreateDrawer open={createOpen} onClose={() => setCreateOpen(false)} />
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
        kicker="in progress"
        value={isLoading ? null : formatNumber(stats?.in_progress)}
        suffix={stats ? `/ ${formatNumber(stats.total_migrations)}` : undefined}
        tone="signal"
        icon={ArrowLeftRight}
      />
      <Tile
        kicker="completed"
        value={isLoading ? null : formatNumber(stats?.completed)}
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
        kicker="success rate"
        value={isLoading ? null : `${(stats?.success_rate ?? 0).toFixed(0)}%`}
        hint={
          stats?.average_duration_seconds
            ? `avg duration · ${formatDuration(stats.average_duration_seconds)}`
            : "no completed runs yet"
        }
        tone="ok"
        icon={Clock}
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
  icon?: typeof ArrowLeftRight;
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
        {suffix && (
          <span className="font-mono text-[12px] text-ink-muted">{suffix}</span>
        )}
      </div>
      {hint && (
        <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint truncate">
          {hint}
        </div>
      )}
    </Panel>
  );
}

/* --------------------------------- toolbar -------------------------------- */

function Toolbar({
  statusFilter,
  onStatusFilter,
  strategyFilter,
  onStrategyFilter,
}: {
  statusFilter: MigrationStatus | "";
  onStatusFilter: (v: MigrationStatus | "") => void;
  strategyFilter: MigrationStrategy | "";
  onStrategyFilter: (v: MigrationStrategy | "") => void;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Select
        aria-label="Filter by status"
        value={statusFilter}
        onChange={(e) => onStatusFilter(e.target.value as MigrationStatus | "")}
        className="w-40 h-9"
      >
        <option value="">all statuses</option>
        {MIGRATION_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s.replace(/_/g, " ")}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by strategy"
        value={strategyFilter}
        onChange={(e) => onStrategyFilter(e.target.value as MigrationStrategy | "")}
        className="w-40 h-9"
      >
        <option value="">all strategies</option>
        {MIGRATION_STRATEGIES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </Select>
    </div>
  );
}

/* ----------------------------------- table -------------------------------- */

function vmName(id: number, vms: Vm[]): string {
  return vms.find((v) => v.id === id)?.name ?? `vm#${id}`;
}

function MigrationTable({
  items,
  isLoading,
  isError,
  onRowClick,
  vms,
  onCreate,
  canCreate,
}: {
  items: Migration[];
  isLoading: boolean;
  isError: boolean;
  onRowClick: (id: number) => void;
  vms: Vm[];
  onCreate: () => void;
  canCreate: boolean;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          failed to load migrations.
        </Callout>
      </div>
    );
  }

  if (isLoading && items.length === 0) {
    return (
      <div className="px-6 pb-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonRow key={i} cols={7} />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={ArrowLeftRight}
        title="no migrations"
        hint={
          canCreate
            ? "pick a vm and trigger a migration to begin."
            : "no migrations yet — ask an operator to create one."
        }
        action={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={14} />}
              onClick={onCreate}
            >
              new migration
            </Button>
          ) : undefined
        }
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
            <TH>progress</TH>
            <TH numeric>duration</TH>
            <TH numeric>updated</TH>
          </TR>
        </THead>
        <tbody>
          {items.map((m, i) => (
            <TR key={m.id} interactive className="sw-mount">
              <TD mono muted>
                <button
                  type="button"
                  onClick={() => onRowClick(m.id)}
                  className="text-left hover:text-signal transition-colors duration-150 tabular"
                  style={{ "--sw-i": i } as React.CSSProperties}
                >
                  #{m.id}
                </button>
              </TD>
              <TD>
                <button
                  type="button"
                  onClick={() => onRowClick(m.id)}
                  className="text-left hover:text-signal transition-colors duration-150 w-full font-medium"
                >
                  {vmName(m.vm_id, vms)}
                </button>
              </TD>
              <TD mono muted>{m.strategy}</TD>
              <TD>
                <Badge variant={STATUS_VARIANT[m.status]}>{m.status.replace(/_/g, " ")}</Badge>
              </TD>
              <TD>
                <ProgressBar
                  value={m.progress_percentage}
                  variant={
                    m.status === "completed"
                      ? "ok"
                      : m.status === "failed"
                        ? "white"
                        : "signal"
                  }
                  className="w-40"
                  showPct
                />
              </TD>
              <TD numeric muted>{formatDuration(m.duration_seconds)}</TD>
              <TD numeric muted>{formatRelativeTime(m.updated_at)}</TD>
            </TR>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

/* ------------------------------ pagination -------------------------------- */

function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onChange: (p: number) => void;
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <div className="flex items-center justify-between">
      <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted tabular">
        {from}–{to} / {total}
      </span>
      <div className="flex items-center gap-1.5">
        <Button
          variant="ghost"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
          leadingIcon={<Icon icon={ChevronLeft} size={14} />}
        >
          previous
        </Button>
        <span className="font-mono text-[11px] tabular text-ink-muted px-2">
          {page} / {totalPages}
        </span>
        <Button
          variant="ghost"
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
          trailingIcon={<Icon icon={ChevronRight} size={14} />}
        >
          next
        </Button>
      </div>
    </div>
  );
}

export { formatDuration, STATUS_VARIANT };
