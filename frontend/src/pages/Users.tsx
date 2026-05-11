import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  UserCheck,
  UserPlus,
  Users as UsersIcon,
  UserX,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { Select } from "@/components/ui/Select";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { TD, TH, THead, TR } from "@/components/ui/Table";
import { Table } from "@/components/ui/Table";
import { listUsers, type UserListItem } from "@/api/users";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { UserCreateDrawer } from "./UserCreateDrawer";

const PAGE_SIZE = 25;
const REFETCH_INTERVAL_MS = 60_000;

type ActiveFilter = "" | "true" | "false";

export default function Users() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("");
  const [createOpen, setCreateOpen] = useState(false);
  const canCreate = useHasPermission("users", "create");

  const params = useMemo(
    () => ({
      skip: (page - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(activeFilter === ""
        ? {}
        : { is_active: activeFilter === "true" }),
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
    <div className="max-w-[1440px] mx-auto p-6 md:p-8 space-y-6">
      <PageHeader
        kicker="administration"
        title="users"
        breadcrumbs={[
          { label: "console" },
          { label: "administration" },
          { label: "users" },
        ]}
        description="Operator accounts. Each user belongs to a tenant and inherits permissions from one or more roles."
        actions={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={16} />}
              onClick={() => setCreateOpen(true)}
            >
              new user
            </Button>
          ) : null
        }
      />

      <StatsStrip total={total} items={items} isLoading={listQuery.isPending} />

      <Panel
        density="compact"
        kicker={
          filtersActive
            ? `filters active · ${total} results`
            : `${total} users registered`
        }
        title="directory"
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
        />
      </Panel>

      <Pagination
        page={page}
        totalPages={totalPages}
        total={total}
        pageSize={PAGE_SIZE}
        onChange={setPage}
      />

      <UserCreateDrawer
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
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
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <Tile kicker="total" value={isLoading ? null : formatNumber(total)} icon={UsersIcon} tone="signal" />
      <Tile
        kicker="active (page)"
        value={isLoading ? null : formatNumber(active)}
        icon={UserCheck}
        tone="ok"
      />
      <Tile
        kicker="inactive (page)"
        value={isLoading ? null : formatNumber(inactive)}
        icon={UserX}
        tone="muted"
      />
      <Tile
        kicker="superusers (page)"
        value={isLoading ? null : formatNumber(superusers)}
        icon={UserPlus}
        tone="err"
      />
    </section>
  );
}

function Tile({
  kicker,
  value,
  icon,
  tone,
}: {
  kicker: string;
  value: string | null;
  icon?: typeof UsersIcon;
  tone: "ok" | "err" | "muted" | "signal";
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
          <span
            className="font-mono tabular text-[28px] leading-none"
            style={{ color }}
          >
            {value}
          </span>
        )}
      </div>
    </Panel>
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
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
        />
        <Input
          aria-label="Search users"
          placeholder="email, name, username…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-8 h-9 w-60"
        />
      </div>
      <Select
        aria-label="Filter by status"
        value={activeFilter}
        onChange={(e) => onActiveFilter(e.target.value as ActiveFilter)}
        className="w-36 h-9"
      >
        <option value="">all statuses</option>
        <option value="true">active</option>
        <option value="false">inactive</option>
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
}: {
  items: UserListItem[];
  isLoading: boolean;
  isError: boolean;
  canCreate: boolean;
  onCreate: () => void;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          failed to load users.
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
        title="no users"
        hint={
          canCreate
            ? "create the first user account to onboard an operator."
            : "no users yet — ask a super-admin to register accounts."
        }
        action={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={14} />}
              onClick={onCreate}
            >
              new user
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <Table>
      <THead>
        <TR>
          <TH>username</TH>
          <TH>email</TH>
          <TH>full name</TH>
          <TH>tenant</TH>
          <TH>role</TH>
          <TH>status</TH>
          <TH numeric>created</TH>
        </TR>
      </THead>
      <tbody>
        {items.map((u) => (
          <TR key={u.id}>
            <TD mono>{u.username}</TD>
            <TD>{u.email}</TD>
            <TD muted>{u.full_name || "—"}</TD>
            <TD mono muted>{u.tenant_id}</TD>
            <TD>
              {u.is_superuser ? (
                <RoleBadge role="super_admin" />
              ) : (
                <span className="font-mono text-[11px] text-ink-muted uppercase tracking-[0.04em]">
                  member
                </span>
              )}
            </TD>
            <TD>
              <Badge variant={u.is_active ? "ok" : "neutral"}>
                {u.is_active ? "active" : "inactive"}
              </Badge>
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
      <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted tabular">
        {from}–{to} / {total}
      </span>
      <div className="flex items-center gap-2">
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
