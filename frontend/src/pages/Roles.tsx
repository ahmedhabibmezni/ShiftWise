import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  Lock,
  Plus,
  Search,
  Shield,
  ShieldCheck,
  Sparkles,
  Users as UsersIcon,
} from "lucide-react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Panel } from "@/components/ui/Panel";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import { getRolesCount, listRoles, type RoleDetail } from "@/api/roles";
import { RoleCreateDrawer } from "./RoleCreateDrawer";
import { RoleDetailDrawer } from "./RoleDetailDrawer";

const REFETCH_MS = 60_000;

function permissionsSummary(perms: Record<string, string[]>): string {
  const entries = Object.entries(perms);
  if (entries.length === 0) return "No permissions";
  const granted = entries.filter(([, v]) => v.length > 0).length;
  return `${granted} resource${granted > 1 ? "s" : ""}`;
}

function wildcardCount(perms: Record<string, string[]>): number {
  return Object.values(perms).filter((v) => v.includes("*")).length;
}

export default function Roles() {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const canCreate = useHasPermission("roles", "create");

  const listQuery = useQuery({
    queryKey: ["roles", "list", search],
    queryFn: () => listRoles({ limit: 200, ...(search.trim() ? { search: search.trim() } : {}) }),
    refetchInterval: REFETCH_MS,
  });

  const countQuery = useQuery({
    queryKey: ["roles", "count"],
    queryFn: () => getRolesCount(),
    refetchInterval: REFETCH_MS,
  });

  const roles = useMemo(() => listQuery.data ?? [], [listQuery.data]);
  const activeRoles = roles.filter((r) => r.is_active).length;
  const inactiveRoles = roles.length - activeRoles;
  void activeRoles;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Roles"
        actions={
          canCreate ? (
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={16} strokeWidth={2.25} />}
              onClick={() => setCreateOpen(true)}
            >
              New Role
            </Button>
          ) : null
        }
      />

      <StatsStrip
        total={countQuery.data?.total}
        system={countQuery.data?.system_roles}
        custom={countQuery.data?.custom_roles}
        inactive={inactiveRoles}
        isLoading={countQuery.isPending}
      />

      <Panel
        kicker={`${roles.length} roles in catalogue`}
        title="Permission Sets"
        action={
          <div className="relative">
            <Icon
              icon={Search}
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
            />
            <Input
              aria-label="Search roles"
              placeholder="Name or description…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 w-56"
            />
          </div>
        }
        bodyClassName="px-0"
      >
        <RoleTable
          roles={roles}
          isLoading={listQuery.isPending}
          isError={listQuery.isError}
          onRowClick={(id) => setSelectedId(id)}
          canCreate={canCreate}
          onCreate={() => setCreateOpen(true)}
        />
      </Panel>

      {/* `key` per selected id remounts the drawer on every open so its
          internal edit/confirm state starts fresh — no reset effect needed. */}
      <RoleDetailDrawer
        key={selectedId ?? "none"}
        id={selectedId}
        onClose={() => setSelectedId(null)}
      />
      <RoleCreateDrawer
        key={createOpen ? "open" : "closed"}
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
    </div>
  );
}

/* ------------------------------- stats strip ------------------------------ */

function StatsStrip({
  total,
  system,
  custom,
  inactive,
  isLoading,
}: {
  total: number | undefined;
  system: number | undefined;
  custom: number | undefined;
  inactive: number;
  isLoading: boolean;
}) {
  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-6">
      <KPIPrimary
        label="Total"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(total)}
        icon={Shield}
        iconTone="accent"
      />
      <KPIPrimary
        label="System"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(system)}
        delta="Immutable"
        deltaTone="neutral"
        icon={Lock}
        iconTone="blue"
      />
      <KPIPrimary
        label="Custom"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(custom)}
        delta="Editable"
        deltaTone="neutral"
        icon={Sparkles}
        iconTone="success"
      />
      <KPIPrimary
        label="Inactive"
        value={isLoading ? <Skeleton className="h-5 w-12" /> : formatNumber(inactive)}
        icon={Ban}
        iconTone={inactive > 0 ? "warn" : "muted"}
      />
    </section>
  );
}

/* --------------------------------- table ---------------------------------- */

function RoleTable({
  roles,
  isLoading,
  isError,
  onRowClick,
  canCreate,
  onCreate,
}: {
  roles: RoleDetail[];
  isLoading: boolean;
  isError: boolean;
  onRowClick: (id: number) => void;
  canCreate: boolean;
  onCreate: () => void;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          Could not load roles. Refresh to retry.
        </Callout>
      </div>
    );
  }

  if (isLoading && roles.length === 0) {
    return (
      <div className="px-6 pb-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonRow key={i} cols={6} />
        ))}
      </div>
    );
  }

  if (roles.length === 0) {
    return (
      <EmptyState
        icon={Shield}
        title="No matching roles"
        hint={
          canCreate
            ? "No role matches the current filters. Create a custom role to scope a new permission set."
            : "No roles match the current filters."
        }
        action={
          canCreate ? (
            <Button
              variant="primary"
              leadingIcon={<Icon icon={Plus} size={14} strokeWidth={2.25} />}
              onClick={onCreate}
            >
              New Role
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
          <TH>Name</TH>
          <TH>Description</TH>
          <TH>Scope</TH>
          <TH>Permissions</TH>
          <TH>Status</TH>
          <TH numeric>Updated</TH>
        </TR>
      </THead>
      <tbody>
        {roles.map((r) => (
          <TR key={r.id} interactive>
            <TD>
              <button
                type="button"
                onClick={() => onRowClick(r.id)}
                className="text-left text-[var(--text-primary)] hover:text-[var(--accent-light)] transition-colors duration-150 w-full font-bold flex items-center gap-2"
              >
                <Icon
                  icon={r.is_system_role ? Lock : ShieldCheck}
                  size={13}
                  className={
                    r.is_system_role
                      ? "text-[var(--text-muted)]"
                      : "text-[var(--alert-success-light)]"
                  }
                />
                {r.name}
              </button>
            </TD>
            <TD muted>{r.description ?? "—"}</TD>
            <TD>
              {r.is_system_role ? (
                <StatusBadge icon={Lock} label="System" tone="info" />
              ) : (
                <StatusBadge label="Custom" tone="muted" />
              )}
            </TD>
            <TD muted>
              <span className="inline-flex items-center gap-2">
                <span className="inline-flex items-center gap-1">
                  <Icon icon={UsersIcon} size={11} className="text-[var(--text-muted)]" />
                  {permissionsSummary(r.permissions)}
                </span>
                {wildcardCount(r.permissions) > 0 && (
                  <span
                    className="text-[10px] uppercase tracking-[0.04em] font-bold"
                    style={{ color: "var(--accent-light)" }}
                    title="Wildcard grants"
                  >
                    · {wildcardCount(r.permissions)}×*
                  </span>
                )}
              </span>
            </TD>
            <TD>
              {r.is_active ? (
                <StatusBadge icon={CheckCircle2} label="Active" tone="ok" />
              ) : (
                <StatusBadge icon={Ban} label="Inactive" tone="muted" />
              )}
            </TD>
            <TD numeric muted>
              {formatRelativeTime(r.updated_at)}
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
  );
}
