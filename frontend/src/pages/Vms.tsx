import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { AlertTriangle, ChevronLeft, ChevronRight, Search, Sparkles, X } from "lucide-react";
import toast from "react-hot-toast";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
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

  const hypervisorsQuery = useQuery({
    queryKey: ["hypervisors", "all-light"],
    queryFn: () => listHypervisors({ skip: 0, limit: 100 }),
    staleTime: 5 * 60_000,
  });

  const totalPages = listQuery.data
    ? Math.max(1, Math.ceil(listQuery.data.total / PAGE_SIZE))
    : 1;
  const items = listQuery.data?.items ?? [];

  return (
    <div className="max-w-[1440px] mx-auto p-8 space-y-6">
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

      <VmTable
        items={items}
        isLoading={listQuery.isPending}
        isError={listQuery.isError}
        onRowClick={(id) => setSelectedId(id)}
        hypervisors={hypervisorsQuery.data?.items ?? []}
      />

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
    <div className="flex items-center gap-3 flex-wrap">
      <div className="relative flex-1 min-w-[200px] max-w-md">
        <Icon
          icon={Search}
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none"
        />
        <Input
          aria-label="Rechercher une vm"
          placeholder="nom, ip ou hostname…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-9"
        />
      </div>
      <Select
        aria-label="Filtrer par statut"
        value={statusFilter}
        onChange={(e) => onStatusFilter(e.target.value as VmStatus | "")}
        className="w-44"
      >
        <option value="">tous les statuts</option>
        {VM_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filtrer par compatibilité"
        value={compatFilter}
        onChange={(e) => onCompatFilter(e.target.value as CompatibilityStatus | "")}
        className="w-44"
      >
        <option value="">toutes compatibilités</option>
        {COMPATIBILITY_STATUSES.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filtrer par hyperviseur"
        value={hypervisorFilter === "" ? "" : String(hypervisorFilter)}
        onChange={(e) => onHypervisorFilter(e.target.value === "" ? "" : Number(e.target.value))}
        className="w-44"
      >
        <option value="">tous les hyperviseurs</option>
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
      <div
        role="alert"
        className="border border-err text-err bg-bg-elev-2 px-4 py-3 font-mono text-[11px] uppercase tracking-[0.04em]"
      >
        Erreur lors du chargement des vms.
      </div>
    );
  }

  return (
    <Table>
      <THead>
        <TR>
          <TH>nom</TH>
          <TH>hyperviseur</TH>
          <TH>os</TH>
          <TH numeric>cpu</TH>
          <TH numeric>ram</TH>
          <TH numeric>disque</TH>
          <TH>statut</TH>
          <TH>compatibilité</TH>
          <TH numeric>vue</TH>
        </TR>
      </THead>
      <tbody>
        {isLoading && items.length === 0 ? (
          <TR>
            <TD muted className="py-6 text-center" colSpan={9}>
              chargement…
            </TD>
          </TR>
        ) : items.length === 0 ? (
          <TR>
            <TD muted className="py-6 text-center" colSpan={9}>
              aucune vm
            </TD>
          </TR>
        ) : (
          items.map((vm) => (
            <TR key={vm.id} interactive>
              <TD>
                <button
                  type="button"
                  onClick={() => onRowClick(vm.id)}
                  className="text-left hover:text-signal transition-colors duration-150 w-full"
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
          ))
        )}
      </tbody>
    </Table>
  );
}

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
      <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted tabular">
        {from}–{to} / {total}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          aria-label="Page précédente"
          leadingIcon={<Icon icon={ChevronLeft} size={16} />}
        >
          précédent
        </Button>
        <span className="font-mono text-[11px] tabular text-ink-muted px-2">
          {page} / {totalPages}
        </span>
        <Button
          variant="ghost"
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Page suivante"
          trailingIcon={<Icon icon={ChevronRight} size={16} />}
        >
          suivant
        </Button>
      </div>
    </div>
  );
}

function VmDetailDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const open = id !== null;

  const detailQuery = useQuery({
    queryKey: ["vm", id],
    queryFn: () => getVm(id!),
    enabled: open,
  });

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeVm(id!, true),
    onSuccess: () => {
      toast.success("Analyse terminée");
      queryClient.invalidateQueries({ queryKey: ["vm", id] });
      queryClient.invalidateQueries({ queryKey: ["vms"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
    },
    onError: (err) => {
      toast.error(describeError(err, "Erreur lors de l'analyse"));
    },
  });

  const vm = detailQuery.data;
  const details = vm?.compatibility_details;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title={vm?.name ?? "machine virtuelle"}
      footer={
        vm && (
          <>
            <Button variant="secondary" onClick={onClose}>
              fermer
            </Button>
            <Button
              variant="primary"
              loading={analyzeMutation.isPending}
              onClick={() => analyzeMutation.mutate()}
              leadingIcon={<Icon icon={Sparkles} size={16} />}
            >
              {details ? "ré-analyser" : "analyser"}
            </Button>
          </>
        )
      }
    >
      {!vm ? (
        <div className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
          chargement…
        </div>
      ) : (
        <div className="space-y-6">
          <VmFacts vm={vm} />
          {details ? (
            <CompatibilityPanel details={details} />
          ) : (
            <section className="border border-line bg-bg-elev-2 p-4 font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
              aucune analyse — cliquez sur «analyser» pour lancer l'analyzer
            </section>
          )}
        </div>
      )}
    </SlideOver>
  );
}

function VmFacts({ vm }: { vm: Vm }) {
  const rows: { label: string; value: string }[] = [
    { label: "id source", value: vm.source_uuid ?? "—" },
    { label: "hostname", value: vm.hostname ?? "—" },
    { label: "ip", value: vm.ip_address ?? "—" },
    { label: "os", value: vm.os_name || vm.os_type || "—" },
    { label: "cpu", value: `${vm.cpu_cores} vcpu` },
    { label: "ram", value: formatMemoryMb(vm.memory_mb) },
    { label: "disque", value: formatGB(vm.disk_gb) },
    { label: "statut", value: vm.status },
    { label: "dernière vue", value: formatRelativeTime(vm.last_seen_at) },
  ];

  return (
    <dl className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="flex justify-between gap-4 border-b border-line pb-2">
          <dt className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
            {r.label}
          </dt>
          <dd className="font-mono text-[12px] tabular text-ink text-right break-all">
            {r.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

const GRADE_TONE: Record<"COMPATIBLE" | "PARTIAL" | "INCOMPATIBLE", BadgeVariant> = {
  COMPATIBLE: "ok",
  PARTIAL: "partial",
  INCOMPATIBLE: "incompatible",
};

function CompatibilityPanel({ details }: { details: NonNullable<Vm["compatibility_details"]> }) {
  return (
    <section className="space-y-4">
      <header className="flex items-center justify-between gap-3">
        <h3 className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
          analyse compatibilité
        </h3>
        <Badge variant={GRADE_TONE[details.grade]}>{details.grade}</Badge>
      </header>

      <div className="grid grid-cols-3 gap-3">
        <ScoreBlock label="score" value={`${details.score}`} />
        <ScoreBlock
          label="moteur"
          value={details.engine + (details.engine === "model" && details.confidence !== null ? ` · ${(details.confidence * 100).toFixed(0)}%` : "")}
        />
        <ScoreBlock
          label="analysée"
          value={formatRelativeTime(details.analyzed_at)}
        />
      </div>

      {details.override_reason && (
        <div className="border border-warn bg-bg-elev-2 p-3 font-mono text-[10px] uppercase tracking-[0.04em] text-warn">
          override · {details.override_reason}
        </div>
      )}

      <RulesGroup
        title="blockers"
        Icon={X}
        color="var(--err)"
        rules={details.blockers}
        emptyLabel="aucun"
      />
      <RulesGroup
        title="warnings"
        Icon={AlertTriangle}
        color="var(--warn)"
        rules={details.warnings}
        emptyLabel="aucun"
      />
    </section>
  );
}

function ScoreBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-bg-elev p-3 flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.05em] text-ink-muted">
        {label}
      </span>
      <span className="font-mono text-[14px] tabular text-ink">{value}</span>
    </div>
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
    <div className="space-y-2">
      <h4 className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted flex items-center gap-2">
        <span style={{ color }} className="inline-flex">
          <IconComponent size={14} strokeWidth={1.5} />
        </span>
        {title}
        <span className="text-ink-muted">· {rules.length}</span>
      </h4>
      {rules.length === 0 ? (
        <div className="font-mono text-[11px] text-ink-muted uppercase tracking-[0.04em]">
          {emptyLabel}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {rules.map((r, i) => (
            <li
              key={`${r.rule}-${i}`}
              className="border-l-2 pl-3 py-1 bg-bg-elev"
              style={{ borderColor: color }}
            >
              <div className="font-mono text-[11px] text-ink">{r.message}</div>
              <div className="font-mono text-[10px] text-ink-muted uppercase tracking-[0.04em]">
                {r.rule}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
