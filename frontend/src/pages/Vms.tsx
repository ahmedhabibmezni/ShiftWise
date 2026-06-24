import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Cpu,
  HardDrive,
  Layers,
  Monitor,
  Search,
  Sparkles,
  X,
  CheckCircle2,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  CompatibilityBadge,
  VmStatusBadge,
  type CompatibilityKey,
  type VmStatusKey,
} from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { Panel } from "@/components/ui/Panel";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricRow } from "@/components/ui/MetricRow";
import { Gauge } from "@/components/ui/Gauge";
import { StackedBar } from "@/components/ui/StackedBar";
import { Callout } from "@/components/ui/Callout";
import { fetchVmStats, type VmStats } from "@/api/stats";
import {
  COMPATIBILITY_STATUSES,
  VM_STATUSES,
  analyzeVm,
  getVm,
  listVms,
  type CompatibilityStatus,
  type Vm,
  type VmStatus,
} from "@/api/vms";
import { listHypervisors, type Hypervisor } from "@/api/hypervisors";
import { totalPages as computeTotalPages } from "@/api/types";
import { formatGB, formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { describeError } from "@/lib/errors";

const PAGE_SIZE = 25;
const REFETCH_INTERVAL_MS = 60_000;

function formatMemoryMb(mb: number | null | undefined): string {
  if (mb == null) return "—";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb} MB`;
}

export default function Vms() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<VmStatus | "">("");
  const [compatFilter, setCompatFilter] = useState<CompatibilityStatus | "">("");
  const [hypervisorFilter, setHypervisorFilter] = useState<number | "">("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const params = useMemo(
    () => ({
      skip: (page - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(compatFilter ? { compatibility: compatFilter } : {}),
      ...(hypervisorFilter !== "" ? { hypervisor_id: hypervisorFilter } : {}),
      ...(search.trim() ? { search: search.trim() } : {}),
    }),
    [page, search, statusFilter, compatFilter, hypervisorFilter],
  );

  const listQuery = useQuery({
    queryKey: ["vms", params],
    queryFn: () => listVms(params),
    refetchInterval: REFETCH_INTERVAL_MS,
    placeholderData: (prev) => prev,
  });

  const statsQuery = useQuery<VmStats>({
    queryKey: ["stats", "vms"],
    queryFn: fetchVmStats,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const hypervisorsQuery = useQuery({
    queryKey: ["hypervisors", "all-light"],
    queryFn: () => listHypervisors({ skip: 0, limit: 100 }),
    staleTime: 5 * 60_000,
  });

  const totalPages = listQuery.data ? computeTotalPages(listQuery.data) : 1;
  const items = listQuery.data?.items ?? [];
  const filtersActive = !!(search || statusFilter || compatFilter || hypervisorFilter !== "");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Virtual Machines"
      />

      <CompatStrip stats={statsQuery.data} isLoading={statsQuery.isPending} />

      <Panel
        kicker={
          filtersActive
            ? `Filters active · ${listQuery.data?.total ?? 0} results`
            : `${listQuery.data?.total ?? 0} VMs discovered`
        }
        title="VM Catalog"
        action={
          <Toolbar
            search={search}
            onSearch={(v) => {
              setSearch(v);
              setPage(1);
            }}
            statusFilter={statusFilter}
            onStatusFilter={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
            compatFilter={compatFilter}
            onCompatFilter={(v) => {
              setCompatFilter(v);
              setPage(1);
            }}
            hypervisorFilter={hypervisorFilter}
            onHypervisorFilter={(v) => {
              setHypervisorFilter(v);
              setPage(1);
            }}
            hypervisors={hypervisorsQuery.data?.items ?? []}
          />
        }
        bodyClassName="px-0"
      >
        <VmTable
          items={items}
          isLoading={listQuery.isPending}
          isError={listQuery.isError}
          onRowClick={(id) => setSelectedId(id)}
          hypervisors={hypervisorsQuery.data?.items ?? []}
          filtersActive={filtersActive}
        />
      </Panel>

      <Pagination
        page={page}
        totalPages={totalPages}
        total={listQuery.data?.total ?? 0}
        pageSize={PAGE_SIZE}
        onChange={setPage}
      />

      <VmDetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}

/* ------------------------------ compat strip ------------------------------ */

function CompatStrip({ stats, isLoading }: { stats: VmStats | undefined; isLoading: boolean }) {
  const compatible = stats?.by_compatibility.COMPATIBLE ?? 0;
  const partial = stats?.by_compatibility.PARTIAL ?? 0;
  const incompatible = stats?.by_compatibility.INCOMPATIBLE ?? 0;
  const unknown = stats?.by_compatibility.UNKNOWN ?? 0;
  const migrated = stats?.by_status.MIGRATED ?? 0;
  const migrating = stats?.by_status.MIGRATING ?? 0;
  const failed = stats?.by_status.FAILED ?? 0;
  const total = stats?.total ?? 0;
  const adoption = total > 0 ? (migrated / total) * 100 : 0;

  const segments = [
    { key: "ok",       label: "Compatible",   value: compatible,   color: "var(--alert-success)" },
    { key: "partial",  label: "Partial",      value: partial,      color: "var(--alert-high)" },
    { key: "ko",       label: "Incompatible", value: incompatible, color: "var(--alert-critical)" },
    { key: "unknown",  label: "Unknown",      value: unknown,      color: "var(--text-muted)" },
  ];

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
      <KPIPrimary
        label="Total Fleet"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(total)}
        icon={Monitor}
        iconTone="accent"
      />
      <KPIPrimary
        label="Migrated"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(migrated)}
        icon={CheckCircle2}
        iconTone="success"
      />
      <KPIPrimary
        label="Migrating"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(migrating)}
        icon={Layers}
        iconTone="accent"
      />
      <KPIPrimary
        label="Failed"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(failed)}
        icon={AlertTriangle}
        iconTone="warn"
      />

      <Panel
        title="Ready for KubeVirt"
        hint="Compatibility · hybrid scoring"
        action={
          <span className="text-[24px] font-bold tabular text-[var(--alert-success-light)] leading-none">
            {total > 0 ? `${((compatible / total) * 100).toFixed(0)}%` : "—"}
          </span>
        }
        className="sm:col-span-2 lg:col-span-3"
      >
        {isLoading ? (
          <Skeleton className="h-14 w-full" />
        ) : (
          <StackedBar segments={segments} height={12} />
        )}
        <div className="mt-3 flex items-center gap-2 text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
          <span aria-hidden className="block h-1.5 w-1.5 rounded-full bg-[var(--accent-light)]" />
          Adoption · {adoption.toFixed(1)}% of fleet already migrated
        </div>
      </Panel>

      <KPIPrimary
        label="Adoption"
        value={`${adoption.toFixed(0)}%`}
        delta={`${migrated}/${total}`}
        deltaTone="neutral"
        icon={CheckCircle2}
        iconTone="blue"
      />
    </section>
  );
}

/* --------------------------------- toolbar -------------------------------- */

function Toolbar({
  search,
  onSearch,
  statusFilter,
  onStatusFilter,
  compatFilter,
  onCompatFilter,
  hypervisorFilter,
  onHypervisorFilter,
  hypervisors,
}: {
  search: string;
  onSearch: (v: string) => void;
  statusFilter: VmStatus | "";
  onStatusFilter: (v: VmStatus | "") => void;
  compatFilter: CompatibilityStatus | "";
  onCompatFilter: (v: CompatibilityStatus | "") => void;
  hypervisorFilter: number | "";
  onHypervisorFilter: (v: number | "") => void;
  hypervisors: Hypervisor[];
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="relative">
        <Icon
          icon={Search}
          size={14}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
        />
        <Input
          aria-label="Search vms"
          placeholder="Name, IP, or hostname…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-9 h-9 w-56"
        />
      </div>
      <Select
        aria-label="Filter by status"
        value={statusFilter}
        onChange={(e) => onStatusFilter(e.target.value as VmStatus | "")}
        className="w-36 h-9"
      >
        <option value="">All Statuses</option>
        {VM_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by compatibility"
        value={compatFilter}
        onChange={(e) => onCompatFilter(e.target.value as CompatibilityStatus | "")}
        className="w-44 h-9"
      >
        <option value="">All Compatibility</option>
        {COMPATIBILITY_STATUSES.map((c) => (
          <option key={c} value={c}>
            {c.charAt(0).toUpperCase() + c.slice(1).toLowerCase()}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by hypervisor"
        value={hypervisorFilter === "" ? "" : String(hypervisorFilter)}
        onChange={(e) =>
          onHypervisorFilter(e.target.value === "" ? "" : Number(e.target.value))
        }
        className="w-44 h-9"
      >
        <option value="">All Hypervisors</option>
        {hypervisors.map((h) => (
          <option key={h.id} value={h.id}>
            {h.name}
          </option>
        ))}
      </Select>
    </div>
  );
}

function hypervisorName(id: number | null, hypervisors: Hypervisor[]): string {
  if (id == null) return "—";
  return hypervisors.find((h) => h.id === id)?.name ?? `#${id}`;
}

/* ----------------------------------- table -------------------------------- */

function VmTable({
  items,
  isLoading,
  isError,
  onRowClick,
  hypervisors,
  filtersActive,
}: {
  items: Vm[];
  isLoading: boolean;
  isError: boolean;
  onRowClick: (id: number) => void;
  hypervisors: Hypervisor[];
  filtersActive: boolean;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          Could not load VMs. Refresh to retry.
        </Callout>
      </div>
    );
  }

  if (isLoading && items.length === 0) {
    return (
      <div className="px-6 pb-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonRow key={i} cols={8} />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={Monitor}
        title={filtersActive ? "No matching VMs" : "No VMs yet"}
        hint={
          filtersActive
            ? "No virtual machine matches the current filters. Clear them to widen the results."
            : "Virtual machines appear here after a hypervisor sync. Run a sync from the Hypervisors page to discover them."
        }
      />
    );
  }

  return (
    <Table className="px-2">
      <THead>
        <TR>
          <TH>Name</TH>
          <TH>Hypervisor</TH>
          <TH>OS</TH>
          <TH numeric>CPU</TH>
          <TH numeric>RAM</TH>
          <TH numeric>Disk</TH>
          <TH>Status</TH>
          <TH>Compat.</TH>
          <TH numeric>Last Seen</TH>
        </TR>
      </THead>
      <tbody>
        {items.map((vm) => (
          <TR key={vm.id} interactive>
            <TD>
              <button
                type="button"
                onClick={() => onRowClick(vm.id)}
                className="text-left text-[var(--text-primary)] hover:text-[var(--accent-light)] transition-colors duration-150 w-full font-bold"
              >
                {vm.name}
              </button>
            </TD>
            <TD muted>{hypervisorName(vm.source_hypervisor_id, hypervisors)}</TD>
            <TD muted>{vm.os_type === "unknown" ? "—" : vm.os_type}</TD>
            <TD numeric>{formatNumber(vm.cpu_cores)}</TD>
            <TD numeric>{formatMemoryMb(vm.memory_mb)}</TD>
            <TD numeric>{formatGB(vm.disk_gb)}</TD>
            <TD>
              <VmStatusBadge status={vm.status.toUpperCase() as VmStatusKey} />
            </TD>
            <TD>
              <CompatibilityBadge
                status={vm.compatibility_status.toUpperCase() as CompatibilityKey}
              />
            </TD>
            <TD numeric muted>
              {formatRelativeTime(vm.last_seen_at)}
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

/* ----------------------------- detail drawer ------------------------------ */

function VmDetailDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const open = id !== null;
  const canAnalyze = useHasPermission("vms", "update");

  const detailQuery = useQuery({
    queryKey: ["vm", id],
    queryFn: () => getVm(id!),
    enabled: open,
  });

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeVm(id!, true),
    onSuccess: () => {
      toast.success("Compatibility analysis complete");
      queryClient.invalidateQueries({ queryKey: ["vm", id] });
      queryClient.invalidateQueries({ queryKey: ["vms"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
    },
    onError: (err) => {
      toast.error(describeError(err, "Compatibility analysis failed"));
    },
  });

  const vm = detailQuery.data;
  const details = vm?.compatibility_details;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title={vm?.name ?? "Virtual Machine"}
      footer={
        vm && (
          <>
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
            {canAnalyze && (
              <Button
                variant="primary"
                loading={analyzeMutation.isPending}
                onClick={() => analyzeMutation.mutate()}
                leadingIcon={<Icon icon={Sparkles} size={14} />}
              >
                {details ? "Re-analyze" : "Analyze"}
              </Button>
            )}
          </>
        )
      }
    >
      {!vm ? (
        <div className="space-y-3">
          <Skeleton className="h-7 w-44" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="space-y-6">
          <VmHero vm={vm} />
          <VmFacts vm={vm} />
          {details ? (
            <CompatibilityPanel details={details} />
          ) : (
            <EmptyState
              icon={Sparkles}
              title="Not analyzed"
              hint="Run the analyzer to compute a hybrid rules + ML compatibility score."
            />
          )}
        </div>
      )}
    </SlideOver>
  );
}

function VmHero({ vm }: { vm: Vm }) {
  return (
    <section className="rounded-2xl bg-[var(--surface-soft)] p-5">
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <VmStatusBadge status={vm.status.toUpperCase() as VmStatusKey} />
        <CompatibilityBadge status={vm.compatibility_status.toUpperCase() as CompatibilityKey} />
        <span className="kicker">{vm.os_name || vm.os_type || "Unknown OS"}</span>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <HeroStat icon={Cpu} label="CPU" value={`${vm.cpu_cores} vCPU`} />
        <HeroStat icon={Layers} label="RAM" value={formatMemoryMb(vm.memory_mb)} />
        <HeroStat icon={HardDrive} label="Disk" value={formatGB(vm.disk_gb)} />
      </div>
    </section>
  );
}

function HeroStat({
  icon,
  label,
  value,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center gap-1.5 kicker">
        <Icon icon={icon} size={11} />
        {label}
      </span>
      <span className="tabular text-[18px] font-bold leading-none text-[var(--text-primary)]">
        {value}
      </span>
    </div>
  );
}

function VmFacts({ vm }: { vm: Vm }) {
  const rows: { label: string; value: string; mono?: boolean }[] = [
    { label: "Source ID", value: vm.source_uuid ?? "—", mono: true },
    { label: "Hostname", value: vm.hostname ?? "—", mono: true },
    { label: "IP Address", value: vm.ip_address ?? "—", mono: true },
    { label: "Last Seen", value: formatRelativeTime(vm.last_seen_at) },
  ];

  return (
    <section>
      <div className="kicker mb-2">Identification</div>
      <div>
        {rows.map((r) => (
          <MetricRow key={r.label} label={r.label} value={r.value} mono={r.mono} />
        ))}
      </div>
    </section>
  );
}

const GRADE_TONE: Record<"COMPATIBLE" | "PARTIAL" | "INCOMPATIBLE", "ok" | "warn" | "err"> = {
  COMPATIBLE: "ok",
  PARTIAL: "warn",
  INCOMPATIBLE: "err",
};

/**
 * Failed rules carry the actionable detail (id + severity + message). The
 * backend's `blockers`/`warnings` are plain message strings, so we prefer the
 * richer `rules` array (filtered to failures) and fall back to the strings
 * when an older analysis lacks the per-rule breakdown.
 */
function failedRules(
  details: NonNullable<Vm["compatibility_details"]>,
  severity: "BLOCKER" | "WARNING",
): DisplayRule[] {
  const fromRules = (details.rules ?? [])
    .filter((r) => !r.passed && r.severity === severity)
    .map((r) => ({ id: r.id, severity, message: r.message }));
  if (fromRules.length > 0) return fromRules;

  const messages = severity === "BLOCKER" ? details.blockers : details.warnings;
  return (messages ?? []).map((message) => ({ id: null, severity, message }));
}

function CompatibilityPanel({ details }: { details: NonNullable<Vm["compatibility_details"]> }) {
  const tone = GRADE_TONE[details.grade];
  const blockers = failedRules(details, "BLOCKER");
  const warnings = failedRules(details, "WARNING");
  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between mb-1">
        <div>
          <div className="kicker mb-1">Analyzer · hybrid scoring</div>
          <div className="flex items-center gap-2">
            <CompatibilityBadge status={details.grade} />
            <span className="text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
              Engine · {details.engine}
              {details.engine === "model" && details.confidence !== null
                ? ` · conf ${(details.confidence * 100).toFixed(0)}%`
                : ""}
            </span>
          </div>
        </div>
        <Gauge value={details.score} label="Score" tone={tone} size={96} />
      </div>

      {details.override_reason && (
        <Callout tone="warn" kicker="Override">
          {details.override_reason}
        </Callout>
      )}

      <RulesGroup
        title="Blockers"
        Icon={X}
        color="var(--alert-critical)"
        rules={blockers}
        emptyLabel="No blockers detected"
      />
      <RulesGroup
        title="Warnings"
        Icon={AlertTriangle}
        color="var(--alert-high)"
        rules={warnings}
        emptyLabel="No warnings"
      />

      <div className="text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
        Analyzed · {formatRelativeTime(details.analyzed_at)}
      </div>
    </section>
  );
}

/** A rule flattened for display — `id` is null when only the message survived. */
type DisplayRule = {
  id: string | null;
  severity: "BLOCKER" | "WARNING";
  message: string;
};

function RulesGroup({
  title,
  Icon: IconComponent,
  color,
  rules,
  emptyLabel,
}: {
  title: string;
  Icon: typeof X;
  color: string;
  rules: DisplayRule[];
  emptyLabel: string;
}) {
  return (
    <div className="space-y-2.5">
      <h4 className="flex items-center gap-2 kicker">
        <span style={{ color }} className="inline-flex">
          <IconComponent size={12} strokeWidth={2} />
        </span>
        <span>{title}</span>
        <span className="text-[var(--text-muted)]">· {rules.length}</span>
      </h4>
      {rules.length === 0 ? (
        <div className="text-[12px] text-[var(--text-muted)] flex items-center gap-2">
          <span aria-hidden className="block h-px w-4 bg-[var(--hairline)]" />
          {emptyLabel}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {rules.map((r, i) => (
            <li
              key={`${r.id ?? "rule"}-${i}`}
              className="flex items-start gap-2.5 rounded-xl bg-[var(--surface-soft)] px-3.5 py-2.5"
            >
              <span
                aria-hidden
                className="shrink-0 inline-flex items-center justify-center mt-[1px]"
                style={{ color }}
              >
                <IconComponent size={13} strokeWidth={2} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-[var(--text-primary)] leading-snug">
                  {r.message}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
                  {r.id && (
                    <>
                      <span>{r.id}</span>
                      <span aria-hidden>·</span>
                    </>
                  )}
                  <span style={{ color }}>{r.severity}</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
