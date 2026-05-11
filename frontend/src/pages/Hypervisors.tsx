import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  ServerOff,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import toast from "react-hot-toast";
import { AxiosError } from "axios";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { Textarea } from "@/components/ui/Textarea";
import { TD, TH, THead, TR } from "@/components/ui/Table";
import { Panel } from "@/components/ui/Panel";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricRow } from "@/components/ui/MetricRow";
import { Sparkline } from "@/components/ui/Sparkline";
import { useQuery as useStatsQuery } from "@tanstack/react-query";
import {
  fetchHypervisorStats,
  type HypervisorStats,
} from "@/api/stats";
import {
  HYPERVISOR_STATUSES,
  HYPERVISOR_TYPES,
  deleteHypervisor,
  getHypervisor,
  listHypervisorVms,
  listHypervisors,
  syncHypervisor,
  updateHypervisor,
  type Hypervisor,
  type HypervisorStatus,
  type HypervisorType,
  type UpdateHypervisorPayload,
} from "@/api/hypervisors";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import type { ApiError } from "@/api/types";
import { Callout } from "@/components/ui/Callout";
import { HypervisorCreateDrawer } from "./HypervisorCreateDrawer";

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
  const [createOpen, setCreateOpen] = useState(false);
  const canCreate = useHasPermission("hypervisors", "create");

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

  const statsQuery = useStatsQuery<HypervisorStats>({
    queryKey: ["stats", "hypervisors"],
    queryFn: fetchHypervisorStats,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const totalPages = listQuery.data
    ? Math.max(1, Math.ceil(listQuery.data.total / PAGE_SIZE))
    : 1;
  const items = listQuery.data?.items ?? [];
  const filtersActive = !!(search || typeFilter || statusFilter);

  return (
    <div className="max-w-[1440px] mx-auto p-6 md:p-8 space-y-6">
      <PageHeader
        kicker="inventory"
        title="hypervisors"
        breadcrumbs={[{ label: "console" }, { label: "inventory" }, { label: "hypervisors" }]}
        description="Discovery sources: vSphere, VMware Workstation, KVM, Hyper-V, Proxmox VE, oVirt/RHV connectors."
        actions={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={16} />}
              onClick={() => setCreateOpen(true)}
            >
              add source
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
            : `${listQuery.data?.total ?? 0} hypervisors registered`
        }
        title="catalogue"
        action={
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
        }
        bodyClassName="px-0"
      >
        <HypervisorTable
          items={items}
          isLoading={listQuery.isPending}
          isError={listQuery.isError}
          onRowClick={(id) => setSelectedId(id)}
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

      <DetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
      <HypervisorCreateDrawer open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

/* ------------------------------- stats strip ------------------------------ */

function StatsStrip({
  stats,
  isLoading,
}: {
  stats: HypervisorStats | undefined;
  isLoading: boolean;
}) {
  const topTypes = Object.entries(stats?.by_type ?? {})
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <Tile
        kicker="active"
        value={isLoading ? null : formatNumber(stats?.active)}
        suffix={stats ? `/ ${formatNumber(stats.total)}` : undefined}
        tone="ok"
        icon={Server}
      />
      <Tile
        kicker="inactive"
        value={isLoading ? null : formatNumber(stats?.inactive)}
        tone="muted"
        icon={ServerOff}
      />
      <Tile
        kicker="errors"
        value={isLoading ? null : formatNumber((stats?.by_status.error ?? 0) + (stats?.by_status.unreachable ?? 0))}
        tone="err"
        icon={TriangleAlert}
      />
      <Tile
        kicker="detected types"
        value={isLoading ? null : `${topTypes.length}`}
        hint={topTypes.length > 0 ? topTypes.map(([t, n]) => `${t.toLowerCase().replace(/_/g, " ")} ${n}`).join(" · ") : undefined}
        tone="signal"
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
  icon?: typeof Server;
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
    <div className="flex items-center gap-2 flex-wrap">
      <div className="relative">
        <Icon
          icon={Search}
          size={14}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
        />
        <Input
          aria-label="Search hypervisors"
          placeholder="name or host…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-8 h-9 w-52"
        />
      </div>
      <Select
        aria-label="Filter by type"
        value={typeFilter}
        onChange={(e) => onTypeFilter(e.target.value as HypervisorType | "")}
        className="w-40 h-9"
      >
        <option value="">all types</option>
        {HYPERVISOR_TYPES.map((t) => (
          <option key={t} value={t}>
            {t.replace(/_/g, " ").toLowerCase()}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by status"
        value={statusFilter}
        onChange={(e) => onStatusFilter(e.target.value as HypervisorStatus | "")}
        className="w-40 h-9"
      >
        <option value="">all statuses</option>
        {HYPERVISOR_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </Select>
    </div>
  );
}

/* ----------------------------------- table -------------------------------- */

function HypervisorTable({
  items,
  isLoading,
  isError,
  onRowClick,
  onCreate,
  canCreate,
}: {
  items: Hypervisor[];
  isLoading: boolean;
  isError: boolean;
  onRowClick: (id: number) => void;
  onCreate: () => void;
  canCreate: boolean;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          failed to load hypervisors.
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
        icon={Server}
        title="no hypervisors"
        hint={
          canCreate
            ? "add a vmware, kvm, hyper-v, proxmox, or ovirt source to begin discovery."
            : "no hypervisors yet — ask an administrator to register a source."
        }
        action={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={14} />}
              onClick={onCreate}
            >
              add source
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <THead>
          <TR>
            <TH>name</TH>
            <TH>type</TH>
            <TH>host</TH>
            <TH>status</TH>
            <TH numeric>vms</TH>
            <TH numeric>migrated</TH>
            <TH numeric>sync</TH>
          </TR>
        </THead>
        <tbody>
          {items.map((h, i) => (
            <TR
              key={h.id}
              interactive
              className="sw-mount"
            >
              <TD>
                <button
                  type="button"
                  onClick={() => onRowClick(h.id)}
                  className="text-left hover:text-signal transition-colors duration-150 w-full font-medium"
                  style={{ "--sw-i": i } as React.CSSProperties}
                >
                  {h.name}
                </button>
              </TD>
              <TD mono muted>
                {h.type.replace(/_/g, " ").toLowerCase()}
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
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ----------------------------- pagination ----------------------------- */

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

/* ------------------------------ detail drawer ----------------------------- */

type EditDraft = {
  name: string;
  description: string;
  host: string;
  port: string;
  username: string;
  password: string;
  verify_ssl: boolean;
  is_active: boolean;
};

function emptyDraft(): EditDraft {
  return {
    name: "",
    description: "",
    host: "",
    port: "",
    username: "",
    password: "",
    verify_ssl: false,
    is_active: true,
  };
}

function draftFrom(h: Hypervisor): EditDraft {
  return {
    name: h.name,
    description: h.description ?? "",
    host: h.host,
    port: h.port != null ? String(h.port) : "",
    username: h.username,
    password: "",
    verify_ssl: h.verify_ssl,
    is_active: h.is_active,
  };
}

function diffPayload(h: Hypervisor, draft: EditDraft): UpdateHypervisorPayload {
  // Only ship fields that actually changed. Two reasons:
  //   1. The backend supports partial updates — sending the full object
  //      is wasteful and risks clobbering anything we forgot about.
  //   2. Password must be omitted entirely when blank, otherwise the
  //      backend's min_length=1 validation would refuse "" and we'd
  //      need a separate branch.
  const payload: UpdateHypervisorPayload = {};
  if (draft.name !== h.name) payload.name = draft.name;
  if (draft.description !== (h.description ?? "")) {
    payload.description = draft.description || null;
  }
  if (draft.host !== h.host) payload.host = draft.host;
  const draftPort = draft.port.trim() === "" ? null : Number(draft.port);
  if (draftPort !== h.port) payload.port = draftPort;
  if (draft.username !== h.username) payload.username = draft.username;
  if (draft.password.length > 0) payload.password = draft.password;
  if (draft.verify_ssl !== h.verify_ssl) payload.verify_ssl = draft.verify_ssl;
  if (draft.is_active !== h.is_active) payload.is_active = draft.is_active;
  return payload;
}

function DetailDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const open = id !== null;
  const canUpdate = useHasPermission("hypervisors", "update");
  const canDelete = useHasPermission("hypervisors", "delete");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<EditDraft>(emptyDraft);

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

  // Reset the draft + leave edit mode whenever a different hypervisor is
  // loaded, or when the drawer closes. Without the reset, switching from
  // hypervisor A (in edit mode) to B would carry A's unsaved changes over.
  useEffect(() => {
    if (detailQuery.data) {
      setDraft(draftFrom(detailQuery.data));
    }
  }, [detailQuery.data]);

  useEffect(() => {
    if (!open) {
      setEditing(false);
    }
  }, [open]);

  const syncMutation = useMutation({
    mutationFn: () => syncHypervisor(id!),
    onSuccess: (data) => {
      toast.success(
        `sync ok · ${data.statistics.total_discovered} discovered · ${data.statistics.new_vms} new`,
      );
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id, "vms"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
    },
    onError: (err) => {
      toast.error(describeError(err, "sync failed."));
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      const payload = diffPayload(detailQuery.data!, draft);
      if (Object.keys(payload).length === 0) {
        // No diff — bail out to avoid a no-op round-trip + 200 with stale data.
        return Promise.resolve(detailQuery.data!);
      }
      return updateHypervisor(id!, payload);
    },
    onSuccess: () => {
      toast.success("hypervisor updated");
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id] });
      setEditing(false);
    },
    onError: (err) => toast.error(describeError(err, "update failed")),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteHypervisor(id!),
    onSuccess: () => {
      toast.success("hypervisor deleted");
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
      onClose();
    },
    onError: (err) => toast.error(describeError(err, "delete failed")),
  });

  const hypervisor = detailQuery.data;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title={hypervisor?.name ?? "hypervisor"}
      footer={
        hypervisor && (
          editing ? (
            <>
              <Button
                variant="secondary"
                onClick={() => {
                  setDraft(draftFrom(hypervisor));
                  setEditing(false);
                }}
                disabled={updateMutation.isPending}
              >
                cancel
              </Button>
              <Button
                variant="primary"
                uppercase
                loading={updateMutation.isPending}
                onClick={() => updateMutation.mutate()}
                leadingIcon={<Icon icon={Save} size={14} />}
              >
                save
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={onClose}>
                close
              </Button>
              {canDelete && (
                <Button
                  variant="secondary"
                  uppercase
                  loading={deleteMutation.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        `delete hypervisor '${hypervisor.name}'? associated vms will be detached.`,
                      )
                    ) {
                      deleteMutation.mutate();
                    }
                  }}
                  leadingIcon={<Icon icon={Trash2} size={14} />}
                >
                  delete
                </Button>
              )}
              {canUpdate && (
                <Button
                  variant="secondary"
                  uppercase
                  onClick={() => setEditing(true)}
                  leadingIcon={<Icon icon={Pencil} size={14} />}
                >
                  edit
                </Button>
              )}
              {canUpdate && (
                <Button
                  variant="primary"
                  loading={syncMutation.isPending}
                  onClick={() => syncMutation.mutate()}
                  leadingIcon={<Icon icon={RefreshCw} size={14} />}
                  uppercase
                >
                  sync now
                </Button>
              )}
            </>
          )
        )
      }
    >
      {!hypervisor ? (
        <div className="space-y-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : editing ? (
        <EditFields draft={draft} onChange={setDraft} hypervisor={hypervisor} />
      ) : (
        <div className="space-y-6">
          <DetailHero hypervisor={hypervisor} />
          <DetailGrid hypervisor={hypervisor} />
          <VmsList isLoading={vmsQuery.isPending} isError={vmsQuery.isError} count={vmsQuery.data?.total_vms ?? 0} />
        </div>
      )}
    </SlideOver>
  );
}

function EditFields({
  draft,
  onChange,
  hypervisor,
}: {
  draft: EditDraft;
  onChange: (next: EditDraft) => void;
  hypervisor: Hypervisor;
}) {
  const set = <K extends keyof EditDraft>(key: K, value: EditDraft[K]) =>
    onChange({ ...draft, [key]: value });

  return (
    <div className="space-y-5">
      <Callout tone="info">
        editing <span className="font-mono">{hypervisor.name}</span> · type +
        ssl-cert path are not editable from this view.
      </Callout>

      <EditField id="ed-name" label="name">
        <Input
          id="ed-name"
          value={draft.name}
          onChange={(e) => set("name", e.target.value)}
        />
      </EditField>

      <EditField id="ed-host" label="host">
        <Input
          id="ed-host"
          value={draft.host}
          onChange={(e) => set("host", e.target.value)}
        />
      </EditField>

      <EditField id="ed-port" label="port">
        <Input
          id="ed-port"
          type="number"
          inputMode="numeric"
          value={draft.port}
          onChange={(e) => set("port", e.target.value)}
        />
      </EditField>

      <EditField id="ed-username" label="username">
        <Input
          id="ed-username"
          autoComplete="username"
          value={draft.username}
          onChange={(e) => set("username", e.target.value)}
        />
      </EditField>

      <EditField
        id="ed-password"
        label="password"
        hint="leave blank to keep the current credential."
      >
        <Input
          id="ed-password"
          type="password"
          autoComplete="new-password"
          value={draft.password}
          placeholder="••••••••"
          onChange={(e) => set("password", e.target.value)}
        />
      </EditField>

      <label className="flex items-center gap-2 cursor-pointer">
        <Checkbox
          checked={draft.verify_ssl}
          onChange={(e) => set("verify_ssl", e.target.checked)}
        />
        <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
          verify ssl certificate
        </span>
      </label>

      <label className="flex items-center gap-2 cursor-pointer">
        <Checkbox
          checked={draft.is_active}
          onChange={(e) => set("is_active", e.target.checked)}
        />
        <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
          active
        </span>
      </label>

      <EditField id="ed-description" label="description">
        <Textarea
          id="ed-description"
          rows={3}
          value={draft.description}
          onChange={(e) => set("description", e.target.value)}
        />
      </EditField>
    </div>
  );
}

function EditField({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted mb-1.5"
      >
        {label}
      </label>
      {children}
      {hint && (
        <div className="mt-1 font-mono text-[10px] text-ink-muted">{hint}</div>
      )}
    </div>
  );
}

function DetailHero({ hypervisor }: { hypervisor: Hypervisor }) {
  const variant = STATUS_VARIANT[hypervisor.status];
  return (
    <section className="border border-line bg-bg-elev p-5 flex items-start justify-between gap-6">
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-3">
          <Badge variant={variant}>{hypervisor.status}</Badge>
          <span className="kicker">{hypervisor.type.replace(/_/g, " ").toLowerCase()}</span>
        </div>
        <div className="font-mono tabular text-[26px] leading-none text-ink">
          {formatNumber(hypervisor.total_vms_discovered)}
          <span className="ml-2 font-mono text-[12px] text-ink-muted">vms discovered</span>
        </div>
        <div className="mt-2 font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
          last sync · {formatRelativeTime(hypervisor.last_sync_at)}
        </div>
      </div>
      <Sparkline
        values={[12, 18, 22, 30, 28, 34, 41, 48, 52, 58, 60, 65, 71, 78]}
        width={140}
        height={48}
        stroke="var(--signal)"
        fill="var(--signal)"
      />
    </section>
  );
}

function DetailGrid({ hypervisor }: { hypervisor: Hypervisor }) {
  const rows: { label: string; value: string }[] = [
    { label: "host", value: hypervisor.host + (hypervisor.port ? `:${hypervisor.port}` : "") },
    { label: "username", value: hypervisor.username },
    { label: "ssl", value: hypervisor.verify_ssl ? "verified" : "disabled" },
    { label: "connection url", value: hypervisor.connection_url },
    { label: "vms discovered", value: formatNumber(hypervisor.total_vms_discovered) },
    { label: "vms migrated", value: formatNumber(hypervisor.total_vms_migrated) },
    { label: "last connection", value: formatRelativeTime(hypervisor.last_successful_connection) },
  ];

  return (
    <section>
      <div className="kicker mb-3">connection</div>
      <div>
        {rows.map((r) => (
          <MetricRow key={r.label} label={r.label} value={r.value} />
        ))}
      </div>
      {hypervisor.last_error && (
        <div className="mt-4">
          <Callout tone="err" kicker="last error">
            <span className="break-all">{hypervisor.last_error}</span>
          </Callout>
        </div>
      )}
    </section>
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
      <div className="kicker mb-3">virtual machines</div>
      {isError ? (
        <div className="font-mono text-[11px] text-err uppercase tracking-[0.04em]">
          load failed
        </div>
      ) : isLoading ? (
        <Skeleton className="h-5 w-40" />
      ) : count === 0 ? (
        <div className="font-mono text-[11px] text-ink-muted uppercase tracking-[0.06em]">
          no vms · trigger a sync
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3 font-mono tabular text-[14px] text-ink">
          <span>{count} vms</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
            details → /vms
          </span>
        </div>
      )}
    </section>
  );
}
