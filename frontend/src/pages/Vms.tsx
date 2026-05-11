import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
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
} from "lucide-react";
import toast from "react-hot-toast";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { Panel } from "@/components/ui/Panel";
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
  type CompatibilityRule,
  type CompatibilityStatus,
  type Vm,
  type VmStatus,
} from "@/api/vms";
import { listHypervisors, type Hypervisor } from "@/api/hypervisors";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import type { ApiError } from "@/api/types";

const PAGE_SIZE = 25;
const REFETCH_INTERVAL_MS = 60_000;

const STATUS_VARIANT: Record<VmStatus, BadgeVariant> = {
  discovered: "neutral",
  analyzing: "info",
  compatible: "ok",
  incompatible: "incompatible",
  partial: "partial",
  migrating: "info",
  migrated: "ok",
  failed: "critical",
  archived: "neutral",
};

const COMPAT_VARIANT: Record<CompatibilityStatus, BadgeVariant> = {
  compatible: "ok",
  partial: "partial",
  incompatible: "incompatible",
  unknown: "neutral",
};

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

function formatGB(gb: number | null | undefined): string {
  if (gb == null || gb === 0) return "—";
  return `${gb} GB`;
}

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

  const totalPages = listQuery.data
    ? Math.max(1, Math.ceil(listQuery.data.total / PAGE_SIZE))
    : 1;
  const items = listQuery.data?.items ?? [];
  const filtersActive = !!(search || statusFilter || compatFilter || hypervisorFilter !== "");

  return (
    <div className="max-w-[1440px] mx-auto p-6 md:p-8 space-y-6">
      <PageHeader
        kicker="inventory"
        title="virtual machines"
        breadcrumbs={[{ label: "console" }, { label: "inventory" }, { label: "vms" }]}
        description="Discovered vms, migration state, and kubevirt compatibility scoring."
      />

      <CompatStrip stats={statsQuery.data} isLoading={statsQuery.isPending} />

      <Panel
        density="compact"
        kicker={
          filtersActive
            ? `filters active · ${listQuery.data?.total ?? 0} results`
            : `${listQuery.data?.total ?? 0} vms discovered`
        }
        title="vm catalogue"
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
    { key: "ok", label: "compatible", value: compatible, color: "var(--ok)" },
    { key: "partial", label: "partial", value: partial, color: "var(--warn)" },
    { key: "ko", label: "incompatible", value: incompatible, color: "var(--err)" },
    { key: "unknown", label: "unknown", value: unknown, color: "var(--ink-faint)" },
  ];

  return (
    <section className="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <Panel
        density="compact"
        kicker="total fleet"
        className="lg:col-span-1"
      >
        {isLoading ? (
          <Skeleton className="h-9 w-28" />
        ) : (
          <div className="flex items-baseline gap-3">
            <span className="font-mono tabular text-[36px] leading-none text-ink">
              {formatNumber(total)}
            </span>
            <span className="font-mono text-[12px] text-ink-muted">vms</span>
          </div>
        )}
        <div className="mt-3 grid grid-cols-3 gap-2">
          <MiniStat label="migrated" value={formatNumber(migrated)} tone="ok" />
          <MiniStat label="migrating" value={formatNumber(migrating)} tone="signal" />
          <MiniStat label="failed" value={formatNumber(failed)} tone="err" />
        </div>
      </Panel>

      <Panel
        density="compact"
        kicker="compatibility · hybrid scoring"
        title="ready for kubevirt"
        action={
          <span className="font-mono tabular text-[24px] text-ok leading-none">
            {total > 0 ? `${((compatible / total) * 100).toFixed(0)}%` : "—"}
          </span>
        }
        className="lg:col-span-2"
      >
        {isLoading ? (
          <Skeleton className="h-14 w-full" />
        ) : (
          <StackedBar segments={segments} height={12} />
        )}
        <div className="mt-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.08em] text-ink-faint">
          <span aria-hidden className="block h-1 w-1 bg-signal rounded-full" />
          adoption · {adoption.toFixed(1)}% of fleet already migrated
        </div>
      </Panel>
    </section>
  );
}

function MiniStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "signal" | "err";
}) {
  const color = tone === "ok" ? "var(--ok)" : tone === "err" ? "var(--err)" : "var(--signal)";
  return (
    <div className="flex flex-col gap-0.5">
      <span className="kicker">{label}</span>
      <span className="font-mono tabular text-[16px] leading-none" style={{ color }}>
        {value}
      </span>
    </div>
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
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
        />
        <Input
          aria-label="Search vms"
          placeholder="name, ip, or hostname…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-8 h-9 w-52"
        />
      </div>
      <Select
        aria-label="Filter by status"
        value={statusFilter}
        onChange={(e) => onStatusFilter(e.target.value as VmStatus | "")}
        className="w-36 h-9"
      >
        <option value="">all statuses</option>
        {VM_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by compatibility"
        value={compatFilter}
        onChange={(e) => onCompatFilter(e.target.value as CompatibilityStatus | "")}
        className="w-40 h-9"
      >
        <option value="">all compatibility</option>
        {COMPATIBILITY_STATUSES.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by hypervisor"
        value={hypervisorFilter === "" ? "" : String(hypervisorFilter)}
        onChange={(e) =>
          onHypervisorFilter(e.target.value === "" ? "" : Number(e.target.value))
        }
        className="w-40 h-9"
      >
        <option value="">all hypervisors</option>
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
}: {
  items: Vm[];
  isLoading: boolean;
  isError: boolean;
  onRowClick: (id: number) => void;
  hypervisors: Hypervisor[];
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          failed to load vms.
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
        title="no vms"
        hint="adjust filters or trigger a sync from the hypervisors page."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table className="border-0">
        <THead>
          <TR>
            <TH>name</TH>
            <TH>hypervisor</TH>
            <TH>os</TH>
            <TH numeric>cpu</TH>
            <TH numeric>ram</TH>
            <TH numeric>disk</TH>
            <TH>status</TH>
            <TH>compat.</TH>
            <TH numeric>seen</TH>
          </TR>
        </THead>
        <tbody>
          {items.map((vm, i) => (
            <TR key={vm.id} interactive className="sw-mount">
              <TD>
                <button
                  type="button"
                  onClick={() => onRowClick(vm.id)}
                  className="text-left hover:text-signal transition-colors duration-150 w-full font-medium"
                  style={{ "--sw-i": i } as React.CSSProperties}
                >
                  {vm.name}
                </button>
              </TD>
              <TD mono muted>
                {hypervisorName(vm.source_hypervisor_id, hypervisors)}
              </TD>
              <TD mono muted>
                {vm.os_type === "unknown" ? "—" : vm.os_type}
              </TD>
              <TD numeric>{formatNumber(vm.cpu_cores)}</TD>
              <TD numeric>{formatMemoryMb(vm.memory_mb)}</TD>
              <TD numeric>{formatGB(vm.disk_gb)}</TD>
              <TD>
                <Badge variant={STATUS_VARIANT[vm.status]}>{vm.status}</Badge>
              </TD>
              <TD>
                <Badge variant={COMPAT_VARIANT[vm.compatibility_status]}>
                  {vm.compatibility_status}
                </Badge>
              </TD>
              <TD numeric muted>
                {formatRelativeTime(vm.last_seen_at)}
              </TD>
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
      toast.success("analysis complete");
      queryClient.invalidateQueries({ queryKey: ["vm", id] });
      queryClient.invalidateQueries({ queryKey: ["vms"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
    },
    onError: (err) => {
      toast.error(describeError(err, "analysis failed"));
    },
  });

  const vm = detailQuery.data;
  const details = vm?.compatibility_details;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title={vm?.name ?? "virtual machine"}
      footer={
        vm && (
          <>
            <Button variant="secondary" onClick={onClose}>
              close
            </Button>
            {canAnalyze && (
              <Button
                variant="primary"
                loading={analyzeMutation.isPending}
                onClick={() => analyzeMutation.mutate()}
                leadingIcon={<Icon icon={Sparkles} size={14} />}
                uppercase
              >
                {details ? "re-analyze" : "analyze"}
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
              title="not analyzed"
              hint="run the analyzer to compute a hybrid rules + ml compatibility score."
            />
          )}
        </div>
      )}
    </SlideOver>
  );
}

function VmHero({ vm }: { vm: Vm }) {
  return (
    <section className="border border-line bg-bg-elev p-5">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Badge variant={STATUS_VARIANT[vm.status]}>{vm.status}</Badge>
        <Badge variant={COMPAT_VARIANT[vm.compatibility_status]}>{vm.compatibility_status}</Badge>
        <span className="kicker">{vm.os_name || vm.os_type || "unknown os"}</span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <HeroStat icon={Cpu} label="cpu" value={`${vm.cpu_cores} vcpu`} />
        <HeroStat icon={Layers} label="ram" value={formatMemoryMb(vm.memory_mb)} />
        <HeroStat icon={HardDrive} label="disk" value={formatGB(vm.disk_gb)} />
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
      <span className="font-mono tabular text-[18px] leading-none text-ink">{value}</span>
    </div>
  );
}

function VmFacts({ vm }: { vm: Vm }) {
  const rows: { label: string; value: string }[] = [
    { label: "source id", value: vm.source_uuid ?? "—" },
    { label: "hostname", value: vm.hostname ?? "—" },
    { label: "ip", value: vm.ip_address ?? "—" },
    { label: "last seen", value: formatRelativeTime(vm.last_seen_at) },
  ];

  return (
    <section>
      <div className="kicker mb-2">identification</div>
      <div>
        {rows.map((r) => (
          <MetricRow key={r.label} label={r.label} value={r.value} />
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
const GRADE_BADGE: Record<"COMPATIBLE" | "PARTIAL" | "INCOMPATIBLE", BadgeVariant> = {
  COMPATIBLE: "ok",
  PARTIAL: "partial",
  INCOMPATIBLE: "incompatible",
};

function CompatibilityPanel({ details }: { details: NonNullable<Vm["compatibility_details"]> }) {
  const tone = GRADE_TONE[details.grade];
  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between mb-1">
        <div>
          <div className="kicker mb-1">analyzer · hybrid scoring</div>
          <div className="flex items-center gap-2">
            <Badge variant={GRADE_BADGE[details.grade]}>{details.grade}</Badge>
            <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted">
              engine · {details.engine}
              {details.engine === "model" && details.confidence !== null
                ? ` · conf ${(details.confidence * 100).toFixed(0)}%`
                : ""}
            </span>
          </div>
        </div>
        <Gauge value={details.score} label="score" tone={tone} />
      </div>

      {details.override_reason && (
        <Callout tone="warn" kicker="override">
          {details.override_reason}
        </Callout>
      )}

      <RulesGroup
        title="blockers"
        Icon={X}
        color="var(--err)"
        rules={details.blockers}
        emptyLabel="no blockers detected"
      />
      <RulesGroup
        title="warnings"
        Icon={AlertTriangle}
        color="var(--warn)"
        rules={details.warnings}
        emptyLabel="no warnings"
      />

      <div className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
        analyzed · {formatRelativeTime(details.analyzed_at)}
      </div>
    </section>
  );
}

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
  rules: CompatibilityRule[];
  emptyLabel: string;
}) {
  return (
    <div className="space-y-2.5">
      <h4 className="flex items-center gap-2 kicker">
        <span style={{ color }} className="inline-flex">
          <IconComponent size={12} strokeWidth={1.75} />
        </span>
        <span>{title}</span>
        <span className="text-ink-faint">· {rules.length}</span>
      </h4>
      {rules.length === 0 ? (
        <div className="font-mono text-[11px] text-ink-faint uppercase tracking-[0.06em] flex items-center gap-2">
          <span aria-hidden className="block h-px w-4 bg-line" />
          {emptyLabel}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {rules.map((r, i) => (
            <li
              key={`${r.rule}-${i}`}
              className="flex items-start gap-2.5 border border-line bg-bg-elev px-3 py-2"
            >
              <span
                aria-hidden
                className="shrink-0 inline-flex items-center justify-center mt-[1px]"
                style={{ color }}
              >
                <IconComponent size={13} strokeWidth={1.75} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[12px] text-ink leading-snug">{r.message}</div>
                <div className="mt-1 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
                  <span>{r.rule}</span>
                  <span className="text-ink-faint" aria-hidden>·</span>
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
