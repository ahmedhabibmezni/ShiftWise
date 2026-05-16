import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  UserCheck,
  UserPlus,
  Users as UsersIcon,
  UserX,
} from "lucide-react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { Select } from "@/components/ui/Select";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { TD, TH, THead, TR } from "@/components/ui/Table";
import { Table } from "@/components/ui/Table";
import { listUsers, type UserListItem } from "@/api/users";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { UserCreateDrawer } from "./UserCreateDrawer";
import { UserDetailDrawer } from "./UserDetailDrawer";

const PAGE_SIZE = 25;
const REFETCH_INTERVAL_MS = 60_000;

type ActiveFilter = "" | "true" | "false";

export default function Users() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("");
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const canCreate = useHasPermission("users", "create");

  const params = useMemo(
    () => ({
      skip: (page - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(activeFilter === "" ? {} : { is_active: activeFilter === "true" }),
    }),
    [page, search, activeFilter],
  );

  const listQuery = useQuery({
    queryKey: ["users", params],
    queryFn: () => listUsers(params),
    refetchInterval: REFETCH_INTERVAL_MS,
    placeholderData: (prev) => prev,
  });

  const total = listQuery.data?.total ?? 0;
  const totalPages = listQuery.data ? Math.max(1, listQuery.data.pages) : 1;
  const items = listQuery.data?.items ?? [];
  const filtersActive = !!(search || activeFilter);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Operator accounts. Each user belongs to a tenant and inherits permissions from one or more roles."
        actions={
          canCreate ? (
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={16} strokeWidth={2.25} />}
              onClick={() => setCreateOpen(true)}
            >
              New User
            </Button>
          ) : null
        }
      />

      <StatsStrip total={total} items={items} isLoading={listQuery.isPending} />

      <Panel
        kicker={
          filtersActive
            ? `Filters active · ${total} results`
            : `${total} users registered`
        }
        title="Directory"
        action={
          <Toolbar
            search={search}
            onSearch={(v) => {
              setSearch(v);
              setPage(1);
            }}
            activeFilter={activeFilter}
            onActiveFilter={(v) => {
              setActiveFilter(v);
              setPage(1);
            }}
          />
        }
        bodyClassName="px-0"
      >
        <UsersTable
          items={items}
          isLoading={listQuery.isPending}
          isError={listQuery.isError}
          canCreate={canCreate}
          onCreate={() => setCreateOpen(true)}
          onRowClick={(id) => setSelectedId(id)}
        />
      </Panel>

      <Pagination
        page={page}
        totalPages={totalPages}
        total={total}
        pageSize={PAGE_SIZE}
        onChange={setPage}
      />

      <UserCreateDrawer open={createOpen} onClose={() => setCreateOpen(false)} />
      <UserDetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}

/* -------------------------------- stats strip ----------------------------- */

function StatsStrip({
  total,
  items,
  isLoading,
}: {
  total: number;
  items: UserListItem[];
  isLoading: boolean;
}) {
  const active = items.filter((u) => u.is_active).length;
  const inactive = items.filter((u) => !u.is_active).length;
  const superusers = items.filter((u) => u.is_superuser).length;

  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-6">
      <KPIPrimary
        label="Total"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(total)}
        icon={UsersIcon}
        iconTone="accent"
      />
      <KPIPrimary
        label="Active (page)"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(active)}
        icon={UserCheck}
        iconTone="success"
      />
      <KPIPrimary
        label="Inactive (page)"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(inactive)}
        icon={UserX}
        iconTone="muted"
      />
      <KPIPrimary
        label="Superusers (page)"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(superusers)}
        icon={UserPlus}
        iconTone="warn"
      />
    </section>
  );
}

/* --------------------------------- toolbar -------------------------------- */

function Toolbar({
  search,
  onSearch,
  activeFilter,
  onActiveFilter,
}: {
  search: string;
  onSearch: (v: string) => void;
  activeFilter: ActiveFilter;
  onActiveFilter: (v: ActiveFilter) => void;
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
          aria-label="Search users"
          placeholder="Email, name, username…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-9 h-9 w-64"
        />
      </div>
      <Select
        aria-label="Filter by status"
        value={activeFilter}
        onChange={(e) => onActiveFilter(e.target.value as ActiveFilter)}
        className="w-36 h-9"
      >
        <option value="">All Statuses</option>
        <option value="true">Active</option>
        <option value="false">Inactive</option>
      </Select>
    </div>
  );
}

/* ---------------------------------- table --------------------------------- */

function UsersTable({
  items,
  isLoading,
  isError,
  canCreate,
  onCreate,
  onRowClick,
}: {
  items: UserListItem[];
  isLoading: boolean;
  isError: boolean;
  canCreate: boolean;
  onCreate: () => void;
  onRowClick: (id: number) => void;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          Could not load users. Refresh to retry.
        </Callout>
      </div>
    );
  }

  if (isLoading && items.length === 0) {
    return (
      <div className="px-6 pb-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonRow key={i} cols={6} />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={UsersIcon}
        title="No users yet"
        hint={
          canCreate
            ? "Create the first user account to onboard an operator."
            : "No users yet. Ask a super-admin to register accounts."
        }
        action={
          canCreate ? (
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={14} strokeWidth={2.25} />}
              onClick={onCreate}
            >
              New User
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <Table className="px-2">
      <THead>
        <TR>
          <TH>Username</TH>
          <TH>Email</TH>
          <TH>Full Name</TH>
          <TH>Tenant</TH>
          <TH>Role</TH>
          <TH>Status</TH>
          <TH numeric>Created</TH>
        </TR>
      </THead>
      <tbody>
        {items.map((u) => (
          <TR key={u.id} interactive>
            <TD>
              <button
                type="button"
                onClick={() => onRowClick(u.id)}
                className="text-left text-[var(--text-primary)] hover:text-[var(--accent-light)] transition-colors duration-150 w-full font-bold"
              >
                {u.username}
              </button>
            </TD>
            <TD>{u.email}</TD>
            <TD muted>{u.full_name || "—"}</TD>
            <TD muted>{u.tenant_id}</TD>
            <TD>
              {u.is_superuser ? (
                <RoleBadge role="super_admin" />
              ) : (
                <span className="text-[11px] text-[var(--text-muted)]">member</span>
              )}
            </TD>
            <TD>
              <StatusBadge
                icon={u.is_active ? CheckCircle2 : Ban}
                label={u.is_active ? "Active" : "Inactive"}
                tone={u.is_active ? "ok" : "muted"}
              />
            </TD>
            <TD numeric muted>
              {formatRelativeTime(u.created_at)}
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
  );
}

/* ------------------------------- pagination ------------------------------- */

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
      <div className="flex items-center gap-2">
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
