import { useMemo, useState } from "react";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plug,
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
import { HypervisorStatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Textarea } from "@/components/ui/Textarea";
import { TD, TH, THead, TR } from "@/components/ui/Table";
import { Panel } from "@/components/ui/Panel";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricRow } from "@/components/ui/MetricRow";
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
  testHypervisorConnectionById,
  updateHypervisor,
  type Hypervisor,
  type HypervisorStatus,
  type HypervisorType,
  type UpdateHypervisorPayload,
} from "@/api/hypervisors";
import { totalPages as computeTotalPages } from "@/api/types";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { describeError } from "@/lib/errors";
import { Callout } from "@/components/ui/Callout";
import { HypervisorCreateDrawer } from "./HypervisorCreateDrawer";
import {
  hypervisorEditSchema,
  portToNumber,
  type HypervisorEditValues,
} from "./hypervisorForm";

const PAGE_SIZE = 25;
const REFETCH_INTERVAL_MS = 60_000;

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

  const totalPages = listQuery.data ? computeTotalPages(listQuery.data) : 1;
  const items = listQuery.data?.items ?? [];
  const filtersActive = !!(search || typeFilter || statusFilter);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Hypervisors"
        actions={
          canCreate ? (
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={16} strokeWidth={2.25} />}
              onClick={() => setCreateOpen(true)}
            >
              New Hypervisor
            </Button>
          ) : null
        }
      />

      <StatsStrip stats={statsQuery.data} isLoading={statsQuery.isPending} />

      <Panel
        kicker={
          filtersActive
            ? `Filters active · ${listQuery.data?.total ?? 0} results`
            : `${listQuery.data?.total ?? 0} hypervisors registered`
        }
        title="Catalog"
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

      {/* `key` per open/selected id remounts each drawer so its internal
          state (edit mode, form fields, confirm dialogs) starts fresh. */}
      <DetailDrawer
        key={selectedId ?? "none"}
        id={selectedId}
        onClose={() => setSelectedId(null)}
      />
      <HypervisorCreateDrawer
        key={createOpen ? "open" : "closed"}
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
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
  const errorCount = (stats?.by_status.error ?? 0) + (stats?.by_status.unreachable ?? 0);
  const types = Object.entries(stats?.by_type ?? {}).filter(([, v]) => v > 0).length;

  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-6">
      <KPIPrimary
        label="Active"
        value={
          isLoading ? (
            <Skeleton className="h-5 w-12" />
          ) : (
            formatNumber(stats?.active)
          )
        }
        delta={stats ? `/ ${formatNumber(stats.total)}` : undefined}
        deltaTone="neutral"
        icon={Server}
        iconTone="success"
      />
      <KPIPrimary
        label="Inactive"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(stats?.inactive)}
        icon={ServerOff}
        iconTone="blue"
      />
      <KPIPrimary
        label="Errors"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(errorCount)}
        icon={TriangleAlert}
        iconTone="warn"
      />
      <KPIPrimary
        label="Types Detected"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : `${types}`}
        icon={Server}
        iconTone="accent"
      />
    </section>
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
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
        />
        <Input
          aria-label="Search hypervisors"
          placeholder="Name or host…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-9 h-9 w-56"
        />
      </div>
      <Select
        aria-label="Filter by type"
        value={typeFilter}
        onChange={(e) => onTypeFilter(e.target.value as HypervisorType | "")}
        className="w-40 h-9"
      >
        <option value="">All Types</option>
        {HYPERVISOR_TYPES.map((t) => (
          <option key={t} value={t}>
            {t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Filter by status"
        value={statusFilter}
        onChange={(e) => onStatusFilter(e.target.value as HypervisorStatus | "")}
        className="w-40 h-9"
      >
        <option value="">All Statuses</option>
        {HYPERVISOR_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s.charAt(0).toUpperCase() + s.slice(1)}
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
          Could not load hypervisors. Refresh to retry.
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
        title="No hypervisors yet"
        hint={
          canCreate
            ? "Add a VMware, KVM, Hyper-V, Proxmox, or oVirt source to begin discovery."
            : "No hypervisors yet. Ask an administrator to register a source."
        }
        action={
          canCreate ? (
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={14} strokeWidth={2.25} />}
              onClick={onCreate}
            >
              New Hypervisor
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto px-2">
      <table className="w-full border-collapse">
        <THead>
          <TR>
            <TH>Name</TH>
            <TH>Type</TH>
            <TH>Host</TH>
            <TH>Status</TH>
            <TH numeric>VMs</TH>
            <TH numeric>Migrated</TH>
            <TH numeric>Last Sync</TH>
          </TR>
        </THead>
        <tbody>
          {items.map((h) => (
            <TR key={h.id} interactive>
              <TD>
                <button
                  type="button"
                  onClick={() => onRowClick(h.id)}
                  className="text-left text-[var(--text-primary)] hover:text-[var(--accent-light)] transition-colors duration-150 w-full font-bold"
                >
                  {h.name}
                </button>
              </TD>
              <TD muted>
                {h.type.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())}
              </TD>
              <TD mono>{h.host}</TD>
              <TD>
                <HypervisorStatusBadge status={h.status} />
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

/* ------------------------------ detail drawer ----------------------------- */

const HYPERVISOR_EDIT_FORM_ID = "hypervisor-edit-form";

/** Seed react-hook-form's default values from the loaded hypervisor. */
function editValuesFrom(h: Hypervisor): HypervisorEditValues {
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

/** Ship only the fields that actually changed (partial PUT — avoids
 *  clobbering server-managed fields; an empty password means "unchanged"). */
function diffPayload(
  h: Hypervisor,
  values: HypervisorEditValues,
): UpdateHypervisorPayload {
  const payload: UpdateHypervisorPayload = {};
  if (values.name !== h.name) payload.name = values.name;
  const nextDescription = values.description ?? "";
  if (nextDescription !== (h.description ?? "")) {
    payload.description = nextDescription || null;
  }
  if (values.host !== h.host) payload.host = values.host;
  const nextPort = portToNumber(values.port);
  if (nextPort !== h.port) payload.port = nextPort;
  if (values.username !== h.username) payload.username = values.username;
  if (values.password.length > 0) payload.password = values.password;
  if (values.verify_ssl !== h.verify_ssl) payload.verify_ssl = values.verify_ssl;
  if (values.is_active !== h.is_active) payload.is_active = values.is_active;
  return payload;
}

function DetailDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const open = id !== null;
  const canUpdate = useHasPermission("hypervisors", "update");
  const canDelete = useHasPermission("hypervisors", "delete");
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Mirrors the EditForm child's in-flight update state so the footer
  // Save button (which lives outside that form) can show a spinner.
  const [savePending, setSavePending] = useState(false);

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
        `Sync ok · ${data.total_discovered} discovered · ${data.new_vms} new`,
      );
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id, "vms"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
    },
    onError: (err) => {
      toast.error(describeError(err, "Sync failed"));
    },
  });

  const testMutation = useMutation({
    mutationFn: () => testHypervisorConnectionById(id!),
    onSuccess: (data) => {
      if (data.success) {
        toast.success(data.message);
      } else {
        toast.error(data.error || data.message);
      }
      // The probe updates the row's status / last_error; refresh so the
      // badge and detail grid reflect it.
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", id] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
    },
    onError: (err) => {
      toast.error(describeError(err, "Connection test failed"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteHypervisor(id!),
    onSuccess: () => {
      toast.success("Hypervisor deleted");
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "vms"] });
      onClose();
    },
    onError: (err) => {
      setConfirmDelete(false);
      toast.error(describeError(err, "Delete failed"));
    },
  });

  const hypervisor = detailQuery.data;

  return (
    <>
    <SlideOver
      open={open}
      onClose={onClose}
      title={hypervisor?.name ?? "Hypervisor"}
      footer={
        hypervisor && (
          editing ? (
            <>
              <Button
                variant="secondary"
                onClick={() => setEditing(false)}
                disabled={savePending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                form={HYPERVISOR_EDIT_FORM_ID}
                variant="primary"
                loading={savePending}
                leadingIcon={<Icon icon={Save} size={14} />}
              >
                Save
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={onClose}>
                Close
              </Button>
              {canDelete && (
                <Button
                  variant="secondary"
                  loading={deleteMutation.isPending}
                  onClick={() => setConfirmDelete(true)}
                  leadingIcon={<Icon icon={Trash2} size={14} />}
                >
                  Delete
                </Button>
              )}
              {canUpdate && (
                <Button
                  variant="secondary"
                  onClick={() => setEditing(true)}
                  leadingIcon={<Icon icon={Pencil} size={14} />}
                >
                  Edit
                </Button>
              )}
              {canUpdate && (
                <Button
                  variant="secondary"
                  loading={testMutation.isPending}
                  onClick={() => testMutation.mutate()}
                  leadingIcon={<Icon icon={Plug} size={14} />}
                >
                  Test Connection
                </Button>
              )}
              {canUpdate && (
                <Button
                  variant="primary"
                  loading={syncMutation.isPending}
                  onClick={() => syncMutation.mutate()}
                  leadingIcon={<Icon icon={RefreshCw} size={14} />}
                >
                  Sync Now
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
        <EditForm
          hypervisor={hypervisor}
          onSavingChange={setSavePending}
          onSaved={() => setEditing(false)}
        />
      ) : (
        <div className="space-y-6">
          <DetailHero hypervisor={hypervisor} />
          <DetailGrid hypervisor={hypervisor} />
          <VmsList isLoading={vmsQuery.isPending} isError={vmsQuery.isError} count={vmsQuery.data?.total_vms ?? 0} />
        </div>
      )}
    </SlideOver>
    {hypervisor && (
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
        loading={deleteMutation.isPending}
        icon={Trash2}
        title="Delete this hypervisor?"
        confirmLabel="Delete hypervisor"
        cancelLabel="Keep hypervisor"
        message={
          <>
            <strong className="font-bold text-[var(--text-primary)]">
              {hypervisor.name}
            </strong>{" "}
            will be removed as a discovery source. Its{" "}
            {formatNumber(hypervisor.total_vms_discovered)} discovered VM
            {hypervisor.total_vms_discovered === 1 ? "" : "s"} are detached and
            stop being synced. Migrated VMs already on OpenShift are not
            affected. This cannot be undone.
          </>
        }
      />
    )}
    </>
  );
}

/**
 * Hypervisor edit form — react-hook-form + Zod (`hypervisorEditSchema`),
 * the same validated pipeline as the create drawer. Previously this was a
 * raw `useState` draft with no inline errors (F9): a blank required field
 * surfaced only as a backend 422.
 *
 * The form owns its update mutation; the Save button lives in the drawer
 * footer and submits via `form={HYPERVISOR_EDIT_FORM_ID}`. `onSavingChange`
 * keeps that out-of-form button's spinner in sync.
 */
function EditForm({
  hypervisor,
  onSavingChange,
  onSaved,
}: {
  hypervisor: Hypervisor;
  onSavingChange: (saving: boolean) => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<HypervisorEditValues>({
    resolver: zodResolver(hypervisorEditSchema),
    defaultValues: editValuesFrom(hypervisor),
  });

  const updateMutation = useMutation({
    mutationFn: (values: HypervisorEditValues) => {
      const payload = diffPayload(hypervisor, values);
      if (Object.keys(payload).length === 0) {
        return Promise.resolve(hypervisor);
      }
      return updateHypervisor(hypervisor.id, payload);
    },
    onMutate: () => onSavingChange(true),
    onSuccess: () => {
      toast.success("Hypervisor updated");
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["hypervisor", hypervisor.id] });
      onSaved();
    },
    onError: (err) => toast.error(describeError(err, "Update failed")),
    onSettled: () => onSavingChange(false),
  });

  const onSubmit: SubmitHandler<HypervisorEditValues> = (values) =>
    updateMutation.mutate(values);

  return (
    <form
      id={HYPERVISOR_EDIT_FORM_ID}
      onSubmit={handleSubmit(onSubmit)}
      noValidate
      className="space-y-5"
    >
      <Callout tone="info">
        Editing <span className="font-bold">{hypervisor.name}</span>. Type and SSL certificate path cannot be changed here.
      </Callout>

      {/* Persistent inline error — a failed update otherwise surfaces only
          as an auto-dismissing toast, easy to miss (F12). */}
      {updateMutation.isError && (
        <Callout tone="err" kicker="Update failed" role="alert">
          {describeError(
            updateMutation.error,
            "Could not save the hypervisor. Check the fields and try again.",
          )}
        </Callout>
      )}

      <EditField id="ed-name" label="Name" error={errors.name?.message}>
        <Input id="ed-name" invalid={!!errors.name} {...register("name")} />
      </EditField>

      <EditField id="ed-host" label="Host" error={errors.host?.message}>
        <Input id="ed-host" invalid={!!errors.host} {...register("host")} />
      </EditField>

      <EditField id="ed-port" label="Port" error={errors.port?.message}>
        <Input
          id="ed-port"
          type="number"
          inputMode="numeric"
          invalid={!!errors.port}
          {...register("port")}
        />
      </EditField>

      <EditField
        id="ed-username"
        label="Username"
        error={errors.username?.message}
      >
        <Input
          id="ed-username"
          autoComplete="username"
          invalid={!!errors.username}
          {...register("username")}
        />
      </EditField>

      <EditField
        id="ed-password"
        label="Password"
        hint="Leave blank to keep the current credential."
        error={errors.password?.message}
      >
        <Input
          id="ed-password"
          type="password"
          autoComplete="new-password"
          placeholder="••••••••"
          invalid={!!errors.password}
          {...register("password")}
        />
      </EditField>

      <label className="flex items-center gap-2.5 cursor-pointer">
        <Checkbox {...register("verify_ssl")} />
        <span className="text-[13px] text-[var(--text-primary)] font-medium">
          Verify SSL certificate
        </span>
      </label>

      <label className="flex items-center gap-2.5 cursor-pointer">
        <Checkbox {...register("is_active")} />
        <span className="text-[13px] text-[var(--text-primary)] font-medium">Active</span>
      </label>

      <EditField
        id="ed-description"
        label="Description"
        error={errors.description?.message}
      >
        <Textarea id="ed-description" rows={3} {...register("description")} />
      </EditField>
    </form>
  );
}

function EditField({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--text-secondary)] mb-1.5"
      >
        {label}
      </label>
      {children}
      {hint && !error && (
        <div className="mt-1.5 text-[11px] text-[var(--text-muted)]">{hint}</div>
      )}
      {error && (
        <div role="alert" className="mt-1.5 text-[12px] text-[var(--alert-critical)]">
          {error}
        </div>
      )}
    </div>
  );
}

function DetailHero({ hypervisor }: { hypervisor: Hypervisor }) {
  return (
    <section className="rounded-2xl bg-[var(--surface-soft)] p-5 flex items-start justify-between gap-6">
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-3">
          <HypervisorStatusBadge status={hypervisor.status} />
          <span className="kicker">
            {hypervisor.type.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())}
          </span>
        </div>
        <div className="text-[28px] font-bold tabular leading-none text-[var(--text-primary)]">
          {formatNumber(hypervisor.total_vms_discovered)}
          <span className="ml-2 text-[12px] font-medium text-[var(--text-secondary)]">
            VMs Discovered
          </span>
        </div>
        <div className="mt-2 text-[11px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
          Last Sync · {formatRelativeTime(hypervisor.last_sync_at)}
        </div>
      </div>
    </section>
  );
}

function DetailGrid({ hypervisor }: { hypervisor: Hypervisor }) {
  const rows: { label: string; value: string; mono?: boolean }[] = [
    {
      label: "Host",
      value: hypervisor.host + (hypervisor.port ? `:${hypervisor.port}` : ""),
      mono: true,
    },
    { label: "Username", value: hypervisor.username },
    { label: "SSL", value: hypervisor.verify_ssl ? "Verified" : "Disabled" },
    { label: "Connection URL", value: hypervisor.connection_url, mono: true },
    { label: "VMs Discovered", value: formatNumber(hypervisor.total_vms_discovered) },
    { label: "VMs Migrated", value: formatNumber(hypervisor.total_vms_migrated) },
    { label: "Last Connection", value: formatRelativeTime(hypervisor.last_successful_connection) },
  ];

  return (
    <section>
      <div className="kicker mb-3">Connection</div>
      <div>
        {rows.map((r) => (
          <MetricRow key={r.label} label={r.label} value={r.value} mono={r.mono} />
        ))}
      </div>
      {hypervisor.last_error && (
        <div className="mt-4">
          <Callout tone="err" kicker="Last error">
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
      <div className="kicker mb-3">Virtual Machines</div>
      {isError ? (
        <div className="text-[11px] text-[var(--alert-critical)] uppercase tracking-[0.04em] font-bold">
          Could not load VMs
        </div>
      ) : isLoading ? (
        <Skeleton className="h-5 w-40" />
      ) : count === 0 ? (
        <div className="text-[12px] text-[var(--text-secondary)]">
          No VMs discovered yet. Run Sync Now to discover them.
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3 tabular text-[14px] text-[var(--text-primary)]">
          <span className="font-bold">{count} VMs</span>
          <span className="text-[11px] text-[var(--text-muted)]">
            See Virtual Machines page for details
          </span>
        </div>
      )}
    </section>
  );
}
