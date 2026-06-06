import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  ArrowRightLeft,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Cpu,
  Monitor,
  Plug,
  Plus,
  RefreshCw,
  Rocket,
  ScanSearch,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Select } from "@/components/ui/Select";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { Panel } from "@/components/ui/Panel";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { PageHeader } from "@/components/ui/PageHeader";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Callout } from "@/components/ui/Callout";
import {
  PipelineStrip,
  type PipelineStageData,
} from "@/components/PipelineStrip";
import {
  MigrationStatusBadge,
  type MigrationStatusKey,
} from "@/components/ui/StatusBadge";
import {
  ACTIVE_MIGRATION_STATUSES,
  MIGRATION_STATUSES,
  MIGRATION_STRATEGIES,
  formatStrategy,
  listMigrations,
  type Migration,
  type MigrationStatus,
  type MigrationStrategy,
} from "@/api/migrations";
import { listVms, type Vm } from "@/api/vms";
import { fetchMigrationStats, type MigrationStats } from "@/api/stats";
import { totalPages as computeTotalPages } from "@/api/types";
import { formatDuration, formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { MigrationCreateDrawer } from "./MigrationCreateDrawer";
import { MigrationDetailDrawer } from "./MigrationDetailDrawer";

const PAGE_SIZE = 25;
const REFETCH_IDLE_MS = 30_000;
const REFETCH_ACTIVE_MS = 5_000;

// One-line description of each pipeline stage, shown in the strip before any
// migration has run so the empty pipeline reads as a diagram, not dead tiles.
const STAGE_BLURB: Record<string, string> = {
  discover: "Scans hypervisors for VMs",
  analyze: "Scores OpenShift fit",
  convert: "Disks to QCOW2",
  adapt: "Guest OS fixups",
  migrate: "Boots on KubeVirt",
};

export default function Migrations() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<MigrationStatus | "">("");
  const [strategyFilter, setStrategyFilter] = useState<MigrationStrategy | "">("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [showFailures, setShowFailures] = useState(false);
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

  const vmsQuery = useQuery({
    queryKey: ["vms", "all-light"],
    queryFn: () => listVms({ skip: 0, limit: 100 }),
    staleTime: 5 * 60_000,
  });

  const totalPages = listQuery.data ? computeTotalPages(listQuery.data) : 1;
  const items = listQuery.data?.items ?? [];
  const filtersActive = !!(statusFilter || strategyFilter);
  const vmList = vmsQuery.data?.items ?? [];

  // Most recent failures in the current view, newest first — fuels the banner.
  const failedMigrations = useMemo(
    () =>
      items
        .filter((m) => m.status === "failed")
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    [items],
  );

  // Toast on a *newly observed* failure. Prime the seen-set on first load so
  // historical failures don't all toast at once; only subsequent transitions
  // (a migration failing while the page is open) raise an alert.
  const seenFailuresRef = useRef<Set<number>>(new Set());
  const primedRef = useRef(false);
  useEffect(() => {
    if (!listQuery.data) return;
    const failedNow = items.filter((m) => m.status === "failed");
    if (!primedRef.current) {
      failedNow.forEach((m) => seenFailuresRef.current.add(m.id));
      primedRef.current = true;
      return;
    }
    for (const m of failedNow) {
      if (seenFailuresRef.current.has(m.id)) continue;
      seenFailuresRef.current.add(m.id);
      const code = m.error_code ? ` · ${m.error_code}` : "";
      toast.error(
        `Migration #${m.id} (${vmName(m.vm_id, vmList)}) failed${code}`,
        { duration: 8_000 },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listQuery.data]);

  // Build pipeline data from current stats
  const pipelineStages: PipelineStageData[] = useMemo(() => {
    const s = statsQuery.data;
    if (!s) {
      return [];
    }
    const total = s.total_migrations;
    const completed = s.completed;
    const inProgress = s.in_progress;
    const pending = s.pending;
    const failed = s.failed;
    const succeededOrInflight = completed + inProgress;
    return [
      {
        key: "discover",
        label: "Discovery",
        icon: ScanSearch,
        count: formatNumber(total),
        meta: total > 0 ? "100% scanned" : STAGE_BLURB.discover,
        progress: total > 0 ? 100 : 0,
        state: total > 0 ? "done" : "pending",
      },
      {
        key: "analyze",
        label: "Analyzer",
        icon: Cpu,
        count: formatNumber(succeededOrInflight + pending),
        meta: total > 0 ? "100% analyzed" : STAGE_BLURB.analyze,
        progress: total > 0 ? 100 : 0,
        state: total > 0 ? "done" : "pending",
      },
      {
        key: "convert",
        label: "Converter",
        icon: RefreshCw,
        count: formatNumber(succeededOrInflight),
        meta:
          total > 0
            ? `${Math.round((succeededOrInflight / total) * 100)}% converted`
            : STAGE_BLURB.convert,
        progress: total > 0 ? (succeededOrInflight / total) * 100 : 0,
        state: succeededOrInflight > 0 ? "active" : "pending",
      },
      {
        key: "adapt",
        label: "Adapter",
        icon: Plug,
        count: formatNumber(inProgress),
        meta:
          total > 0
            ? `${Math.round((inProgress / total) * 100)}% adapted`
            : STAGE_BLURB.adapt,
        progress: total > 0 ? (inProgress / total) * 100 : 0,
        state: inProgress > 0 ? "active" : "pending",
      },
      {
        key: "migrate",
        label: "Migrator",
        icon: Rocket,
        count: formatNumber(completed),
        meta:
          total > 0
            ? `${Math.round((completed / total) * 100)}% migrated`
            : STAGE_BLURB.migrate,
        progress: total > 0 ? (completed / total) * 100 : 0,
        state: completed > 0 && failed === 0 ? "done" : completed > 0 ? "active" : "pending",
      },
    ];
  }, [statsQuery.data]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Migrations"
        actions={
          canCreate ? (
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={16} strokeWidth={2.25} />}
              onClick={() => setCreateOpen(true)}
            >
              New Migration
            </Button>
          ) : null
        }
      />

      <StatsStrip stats={statsQuery.data} isLoading={statsQuery.isPending} />

      {failedMigrations.length > 0 && (
        <div className="flex flex-col gap-3">
          <div>
            <Button
              variant="secondary"
              size="sm"
              leadingIcon={<Icon icon={XCircle} size={14} />}
              onClick={() => setShowFailures((s) => !s)}
            >
              {showFailures
                ? "Hide failure causes"
                : `View failure causes (${failedMigrations.length})`}
            </Button>
          </div>
          {showFailures && (
            <FailureBanner
              migrations={failedMigrations}
              vms={vmList}
              onSelect={setSelectedId}
            />
          )}
        </div>
      )}

      <Panel
        title="Migration Pipeline"
        hint={
          (statsQuery.data?.total_migrations ?? 0) > 0
            ? `Live state across ${statsQuery.data?.total_migrations} jobs`
            : "The five stages every VM clears on its way to OpenShift"
        }
      >
        {statsQuery.isPending || pipelineStages.length === 0 ? (
          <Skeleton className="h-[120px] w-full" />
        ) : (
          <PipelineStrip stages={pipelineStages} />
        )}
      </Panel>

      <Panel
        kicker={
          filtersActive
            ? `Filters active · ${listQuery.data?.total ?? 0} results`
            : `${listQuery.data?.total ?? 0} migrations recorded`
        }
        title="Pipeline Log"
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

      {/* `key` per open/selected id remounts each drawer so its internal
          state (confirm dialogs, form fields) starts fresh on every open. */}
      <MigrationDetailDrawer
        key={selectedId ?? "none"}
        id={selectedId}
        onClose={() => setSelectedId(null)}
        vms={vmsQuery.data?.items ?? []}
      />
      <MigrationCreateDrawer
        key={createOpen ? "open" : "closed"}
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
    </div>
  );
}

/* ------------------------------ failure banner ---------------------------- */

/**
 * Surfaces the main issue behind failed migrations directly on the list page,
 * so an operator sees *why* a migration failed (error code + message) without
 * opening the drawer. Shows the most recent failures; each row opens its
 * migration. Pairs with the transition toast above for immediate awareness.
 */
function FailureBanner({
  migrations,
  vms,
  onSelect,
}: {
  migrations: Migration[];
  vms: Vm[];
  onSelect: (id: number) => void;
}) {
  const MAX_SHOWN = 3;
  const shown = migrations.slice(0, MAX_SHOWN);
  const extra = migrations.length - shown.length;

  return (
    <Callout
      tone="err"
      role="alert"
      kicker={
        migrations.length === 1
          ? "Migration failed"
          : `${migrations.length} migrations failed`
      }
    >
      <ul className="space-y-2">
        {shown.map((m) => (
          <li key={m.id}>
            <button
              type="button"
              onClick={() => onSelect(m.id)}
              className="text-left w-full hover:opacity-80 transition-opacity duration-150"
            >
              <span className="font-bold">
                #{m.id} · {vmName(m.vm_id, vms)}
              </span>
              {m.error_code && (
                <span className="ml-2 text-[11px] uppercase tracking-[0.04em] font-bold opacity-80">
                  {m.error_code}
                </span>
              )}
              <span className="block text-[12px] opacity-90 break-words">
                {m.error_message ?? "No diagnostic message was recorded."}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {extra > 0 && (
        <div className="mt-2 text-[11px] uppercase tracking-[0.04em] font-bold opacity-80">
          + {extra} more failed
        </div>
      )}
    </Callout>
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
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-6">
      <KPIPrimary
        label="In Progress"
        value={
          isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(stats?.in_progress)
        }
        delta={stats ? `/ ${formatNumber(stats.total_migrations)}` : undefined}
        deltaTone="neutral"
        icon={ArrowRightLeft}
        iconTone="accent"
      />
      <KPIPrimary
        label="Completed"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(stats?.completed)}
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
        label="Success Rate"
        value={
          isLoading ? <Skeleton className="h-5 w-12" /> : `${(stats?.success_rate ?? 0).toFixed(0)}%`
        }
        delta={
          stats?.average_duration_seconds
            ? formatDuration(stats.average_duration_seconds)
            : undefined
        }
        deltaTone="neutral"
        icon={Clock}
        iconTone="blue"
      />
    </section>
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
        className="w-44 h-9"
      >
        <option value="">All Statuses</option>
        {MIGRATION_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by strategy"
        value={strategyFilter}
        onChange={(e) => onStrategyFilter(e.target.value as MigrationStrategy | "")}
        className="w-44 h-9"
      >
        <option value="">All Strategies</option>
        {MIGRATION_STRATEGIES.map((s) => (
          <option key={s} value={s}>
            {s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()}
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

/**
 * First-run empty state for the pipeline log. The strip above already names
 * the five stages; this panel's job is to route the operator to the first
 * action and name its prerequisite (a compatibility-checked VM).
 */
function MigrationsEmptyState({
  onCreate,
  canCreate,
}: {
  onCreate: () => void;
  canCreate: boolean;
}) {
  const navigate = useNavigate();
  return (
    <EmptyState
      icon={Rocket}
      title="No migrations yet"
      hint={
        canCreate
          ? "A migration carries one virtual machine through the five stages above and onto OpenShift Virtualization. Start with a VM that has cleared compatibility analysis."
          : "No migrations have run yet. An operator with migration rights launches the first one."
      }
      action={
        canCreate ? (
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={14} strokeWidth={2.25} />}
              onClick={onCreate}
            >
              New Migration
            </Button>
            <Button
              variant="secondary"
              leadingIcon={<Icon icon={Monitor} size={14} />}
              onClick={() => navigate("/vms")}
            >
              Review VM readiness
            </Button>
          </div>
        ) : undefined
      }
    />
  );
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
          Could not load migrations. Refresh to retry.
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
    return <MigrationsEmptyState onCreate={onCreate} canCreate={canCreate} />;
  }

  return (
    <Table className="px-2">
      <THead>
        <TR>
          <TH>#</TH>
          <TH>VM</TH>
          <TH>Strategy</TH>
          <TH>Status</TH>
          <TH>Progress</TH>
          <TH numeric>Duration</TH>
          <TH numeric>Updated</TH>
        </TR>
      </THead>
      <tbody>
        {items.map((m) => (
          <TR key={m.id} interactive>
            <TD muted>
              <button
                type="button"
                onClick={() => onRowClick(m.id)}
                className="text-left hover:text-[var(--accent-light)] transition-colors duration-200 tabular font-bold text-[var(--text-primary)]"
              >
                #{m.id}
              </button>
            </TD>
            <TD>
              <button
                type="button"
                onClick={() => onRowClick(m.id)}
                className="text-left text-[var(--text-primary)] hover:text-[var(--accent-light)] transition-colors duration-200 w-full font-bold"
              >
                {vmName(m.vm_id, vms)}
              </button>
            </TD>
            <TD muted>{formatStrategy(m.strategy)}</TD>
            <TD>
              <MigrationStatusBadge status={m.status.toUpperCase() as MigrationStatusKey} />
            </TD>
            <TD>
              <ProgressBar
                value={m.progress_percentage}
                variant={
                  m.status === "completed"
                    ? "ok"
                    : m.status === "failed"
                      ? "err"
                      : "signal"
                }
                className="w-40"
                showPct
              />
            </TD>
            <TD numeric muted>
              {formatDuration(m.duration_seconds)}
            </TD>
            <TD numeric muted>
              {formatRelativeTime(m.updated_at)}
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
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
      <span className="text-[11px] uppercase tracking-[0.04em] font-bold text-[var(--text-secondary)] tabular">
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1.5">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
          leadingIcon={<Icon icon={ChevronLeft} size={14} />}
        >
          Previous
        </Button>
        <span className="text-[11px] tabular text-[var(--text-secondary)] px-2">
          {page} / {totalPages}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
          trailingIcon={<Icon icon={ChevronRight} size={14} />}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
