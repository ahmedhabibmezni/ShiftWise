import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, RefreshCw, Search } from "lucide-react";
import toast from "react-hot-toast";
import { AxiosError } from "axios";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import {
  HYPERVISOR_STATUSES,
  HYPERVISOR_TYPES,
  getHypervisor,
  listHypervisorVms,
  listHypervisors,
  syncHypervisor,
  type Hypervisor,
  type HypervisorStatus,
  type HypervisorType,
} from "@/api/hypervisors";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import type { ApiError } from "@/api/types";

const PAGE_SIZE = 25;
const REFETCH_INTERVAL_MS = 60_000;

const STATUS_VARIANT: Record<HypervisorStatus, BadgeVariant> = {
  active: "ok",
  inactive: "neutral",
  error: "critical",
  unreachable: "warn",
  authenticating: "info",
  discovering: "info",
  unknown: "neutral",
};

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

export default function Hypervisors() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<HypervisorType | "">("");
  const [statusFilter, setStatusFilter] = useState<HypervisorStatus | "">("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const params = useMemo(
    () => ({
      skip: (page - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      ...(typeFilter ? { type: typeFilter } : {}),
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(search.trim() ? { search: search.trim() } : {}),
    }),
    [page, search, typeFilter, statusFilter],
  );

  const listQuery = useQuery({
    queryKey: ["hypervisors", params],
    queryFn: () => listHypervisors(params),
    refetchInterval: REFETCH_INTERVAL_MS,
    placeholderData: (prev) => prev,
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
        typeFilter={typeFilter}
        onTypeFilter={(v) => {
          setTypeFilter(v);
          setPage(1);
        }}
        statusFilter={statusFilter}
        onStatusFilter={(v) => {
          setStatusFilter(v);
          setPage(1);
        }}
      />

      <HypervisorTable
        items={items}
        isLoading={listQuery.isPending}
        isError={listQuery.isError}
        onRowClick={(id) => setSelectedId(id)}
      />

      <Pagination
        page={page}
        totalPages={totalPages}
        total={listQuery.data?.total ?? 0}
        pageSize={PAGE_SIZE}
        onChange={setPage}
      />

      <DetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}

function Toolbar({
  search,
  onSearch,
  typeFilter,
  onTypeFilter,
  statusFilter,
  onStatusFilter,
}: {
  search: string;
  onSearch: (v: string) => void;
  typeFilter: HypervisorType | "";
  onTypeFilter: (v: HypervisorType | "") => void;
  statusFilter: HypervisorStatus | "";
  onStatusFilter: (v: HypervisorStatus | "") => void;
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
          aria-label="Rechercher un hyperviseur"
          placeholder="nom ou host…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-9"
        />
      </div>
      <Select
        aria-label="Filtrer par type"
        value={typeFilter}
        onChange={(e) => onTypeFilter(e.target.value as HypervisorType | "")}
        className="w-44"
      >
        <option value="">tous les types</option>
        {HYPERVISOR_TYPES.map((t) => (
          <option key={t} value={t}>
            {t.replace(/_/g, " ")}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filtrer par statut"
        value={statusFilter}
        onChange={(e) => onStatusFilter(e.target.value as HypervisorStatus | "")}
        className="w-44"
      >
        <option value="">tous les statuts</option>
        {HYPERVISOR_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </Select>
      <Button variant="primary" disabled title="Bientôt disponible">
        + ajouter
      </Button>
    </div>
  );
}

function HypervisorTable({
  items,
  isLoading,
  isError,
  onRowClick,
}: {
  items: Hypervisor[];
  isLoading: boolean;
  isError: boolean;
  onRowClick: (id: number) => void;
}) {
  if (isError) {
    return (
      <div
        role="alert"
        className="border border-err text-err bg-bg-elev-2 px-4 py-3 font-mono text-[11px] uppercase tracking-[0.04em]"
      >
        Erreur lors du chargement des hyperviseurs.
      </div>
    );
  }

  return (
    <Table>
      <THead>
        <TR>
          <TH>nom</TH>
          <TH>type</TH>
          <TH>host</TH>
          <TH>statut</TH>
          <TH numeric>vms</TH>
          <TH numeric>migrées</TH>
          <TH numeric>dernière sync</TH>
        </TR>
      </THead>
      <tbody>
        {isLoading && items.length === 0 ? (
          <TR>
            <TD muted className="py-6 text-center" colSpan={7}>
              chargement…
            </TD>
          </TR>
        ) : items.length === 0 ? (
          <TR>
            <TD muted className="py-6 text-center" colSpan={7}>
              aucun hyperviseur
            </TD>
          </TR>
        ) : (
          items.map((h) => (
            <TR key={h.id} interactive>
              <TD>
                <button
                  type="button"
                  onClick={() => onRowClick(h.id)}
                  className="text-left hover:text-signal transition-colors duration-150 w-full"
                >
                  {h.name}
                </button>
              </TD>
              <TD mono muted>
                {h.type.replace(/_/g, " ")}
              </TD>
              <TD mono>{h.host}</TD>
              <TD>
                <Badge variant={STATUS_VARIANT[h.status]}>{h.status}</Badge>
              </TD>
              <TD numeric>{formatNumber(h.total_vms_discovered)}</TD>
              <TD numeric>{formatNumber(h.total_vms_migrated)}</TD>
              <TD numeric muted>
                {formatRelativeTime(h.last_sync_at)}
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

function DetailDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const open = id !== null;

  const detailQuery = useQuery({
    queryKey: ["hypervisor", id],
    queryFn: () => getHypervisor(id!),
    enabled: open,
  });

  const vmsQuery = useQuery({
    queryKey: ["hypervisor", id, "vms"],
    queryFn: () => listHypervisorVms(id!),
    enabled: open,
  });

  const syncMutation = useMutation({
    mutationFn: () => syncHypervisor(id!),
    onSuccess: (data) => {
      toast.success(
        `Sync OK · ${data.statistics.total_discovered} découvertes · ${data.statistics.new_vms} nouvelles`,
      );
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id, "vms"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
    },
    onError: (err) => {
      toast.error(describeError(err, "Échec de la synchronisation."));
    },
  });

  const hypervisor = detailQuery.data;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title={hypervisor?.name ?? "hyperviseur"}
      footer={
        hypervisor && (
          <>
            <Button variant="secondary" onClick={onClose}>
              fermer
            </Button>
            <Button
              variant="primary"
              loading={syncMutation.isPending}
              onClick={() => syncMutation.mutate()}
              leadingIcon={<Icon icon={RefreshCw} size={16} />}
            >
              synchroniser
            </Button>
          </>
        )
      }
    >
      {!hypervisor ? (
        <div className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
          chargement…
        </div>
      ) : (
        <div className="space-y-6">
          <DetailGrid hypervisor={hypervisor} />
          <VmsList isLoading={vmsQuery.isPending} isError={vmsQuery.isError} count={vmsQuery.data?.total_vms ?? 0} />
        </div>
      )}
    </SlideOver>
  );
}

function DetailGrid({ hypervisor }: { hypervisor: Hypervisor }) {
  const rows: { label: string; value: string }[] = [
    { label: "type", value: hypervisor.type.replace(/_/g, " ") },
    { label: "host", value: hypervisor.host + (hypervisor.port ? `:${hypervisor.port}` : "") },
    { label: "username", value: hypervisor.username },
    { label: "statut", value: hypervisor.status },
    { label: "ssl", value: hypervisor.verify_ssl ? "vérifié" : "désactivé" },
    { label: "url", value: hypervisor.connection_url },
    { label: "vms découvertes", value: formatNumber(hypervisor.total_vms_discovered) },
    { label: "vms migrées", value: formatNumber(hypervisor.total_vms_migrated) },
    { label: "dernière sync", value: formatRelativeTime(hypervisor.last_sync_at) },
    { label: "dernière connexion", value: formatRelativeTime(hypervisor.last_successful_connection) },
  ];

  return (
    <dl className="space-y-3">
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
      {hypervisor.last_error && (
        <div className="border border-err bg-bg-elev-2 p-3">
          <div className="font-mono text-[10px] uppercase tracking-[0.05em] text-err mb-1">
            dernière erreur
          </div>
          <div className="font-mono text-[11px] text-ink break-all">
            {hypervisor.last_error}
          </div>
        </div>
      )}
    </dl>
  );
}

function VmsList({
  isLoading,
  isError,
  count,
}: {
  isLoading: boolean;
  isError: boolean;
  count: number;
}) {
  return (
    <section>
      <h3 className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted mb-2 border-b border-line pb-2">
        machines virtuelles
      </h3>
      {isError ? (
        <div className="font-mono text-[11px] text-err uppercase tracking-[0.04em]">
          erreur de chargement
        </div>
      ) : isLoading ? (
        <div className="font-mono text-[11px] text-ink-muted uppercase tracking-[0.04em]">
          chargement…
        </div>
      ) : count === 0 ? (
        <div className="font-mono text-[11px] text-ink-muted uppercase tracking-[0.04em]">
          aucune vm — lancez une synchronisation
        </div>
      ) : (
        <div className="font-mono text-[12px] tabular text-ink">
          {count} vms · détail dans /vms (à venir)
        </div>
      )}
    </section>
  );
}
