import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Ban, CheckCircle2, Pencil, Save, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Checkbox } from "@/components/ui/Checkbox";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { MetricRow } from "@/components/ui/MetricRow";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  deleteUser,
  getUser,
  listRoles,
  updateUser,
  type UpdateUserPayload,
} from "@/api/users";
import type { ApiError, User } from "@/api/types";
import { formatRelativeTime } from "@/lib/format";
import {
  isSuperAdminUser,
  primaryRole,
  SUPER_ADMIN_ROLE,
  useHasPermission,
} from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

type Draft = {
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  password: string;
  is_active: boolean;
  role_ids: number[];
};

function emptyDraft(): Draft {
  return {
    email: "",
    username: "",
    first_name: "",
    last_name: "",
    password: "",
    is_active: true,
    role_ids: [],
  };
}

function draftFrom(u: User): Draft {
  return {
    email: u.email,
    username: u.username,
    first_name: u.first_name ?? "",
    last_name: u.last_name ?? "",
    password: "",
    is_active: u.is_active,
    role_ids: u.roles.map((r) => r.id),
  };
}

function diffPayload(u: User, draft: Draft): UpdateUserPayload {
  // Ship only what actually changed — same rationale as the hypervisor diff:
  // partial updates avoid clobbering unknown fields, and the password is
  // forbidden as an empty string by the backend's min_length validator.
  const payload: UpdateUserPayload = {};
  if (draft.email !== u.email) payload.email = draft.email;
  if (draft.username !== u.username) payload.username = draft.username;
  if (draft.first_name !== (u.first_name ?? "")) {
    payload.first_name = draft.first_name || null;
  }
  if (draft.last_name !== (u.last_name ?? "")) {
    payload.last_name = draft.last_name || null;
  }
  if (draft.password.length > 0) payload.password = draft.password;
  if (draft.is_active !== u.is_active) payload.is_active = draft.is_active;
  const currentIds = u.roles.map((r) => r.id).sort();
  const draftIds = [...draft.role_ids].sort();
  if (JSON.stringify(currentIds) !== JSON.stringify(draftIds)) {
    payload.role_ids = draft.role_ids;
  }
  return payload;
}

export function UserDetailDrawer({
  id,
  onClose,
}: {
  id: number | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = id !== null;
  const canUpdate = useHasPermission("users", "update");
  const canDelete = useHasPermission("users", "delete");
  const me = useAuthStore((s) => s.user);
  const isSelf = !!me && me.id === id;
  const meIsSuperuser = me?.is_superuser ?? false;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["user", id],
    queryFn: () => getUser(id!),
    enabled: open,
  });

  const rolesQuery = useQuery({
    queryKey: ["roles", "all"],
    queryFn: listRoles,
    enabled: open,
    staleTime: 5 * 60_000,
  });

  // A non-superuser cannot grant the super_admin role — drop it from the
  // edit form's role list so it is never offered.
  const editableRoles = useMemo(
    () =>
      (rolesQuery.data ?? []).filter(
        (r) => meIsSuperuser || r.name !== SUPER_ADMIN_ROLE,
      ),
    [rolesQuery.data, meIsSuperuser],
  );

  useEffect(() => {
    if (detailQuery.data) setDraft(draftFrom(detailQuery.data));
  }, [detailQuery.data]);

  useEffect(() => {
    if (!open) {
      setEditing(false);
      setConfirmDelete(false);
    }
  }, [open]);

  const setAuthUser = useAuthStore((s) => s.setUser);

  const updateMutation = useMutation({
    mutationFn: () => {
      const payload = diffPayload(detailQuery.data!, draft);
      if (Object.keys(payload).length === 0) {
        return Promise.resolve(detailQuery.data!);
      }
      return updateUser(id!, payload);
    },
    onSuccess: (next) => {
      toast.success("User updated");
      queryClient.invalidateQueries({ queryKey: ["user", id] });
      queryClient.invalidateQueries({ queryKey: ["users"] });
      // If the operator just edited their own profile, push the new user
      // object straight into the auth store. /me is read once by AuthGate
      // at boot — there's no React Query for it — so invalidating a
      // synthetic "auth/me" key wouldn't actually refresh anything. The
      // sidebar and route guards all read from the store.
      if (isSelf) {
        setAuthUser(next);
      }
      setEditing(false);
    },
    onError: (err) => toast.error(describeError(err, "Update failed")),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteUser(id!),
    onSuccess: () => {
      toast.success("User deleted");
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (err) => {
      setConfirmDelete(false);
      toast.error(describeError(err, "Delete failed"));
    },
  });

  const user = detailQuery.data;
  // A non-superuser may not modify a super-admin account — mirrors the
  // backend guard in update_user / delete_user. Self-edits stay allowed.
  const targetIsSuperAdmin = !!user && isSuperAdminUser(user);
  const canEditUser =
    canUpdate && (meIsSuperuser || isSelf || !targetIsSuperAdmin);
  const canDeleteUser =
    canDelete && !isSelf && (meIsSuperuser || !targetIsSuperAdmin);

  return (
    <>
    <SlideOver
      open={open}
      onClose={onClose}
      title={user ? user.username : "User"}
      footer={
        user && (
          editing ? (
            <>
              <Button
                variant="secondary"
                onClick={() => {
                  setDraft(draftFrom(user));
                  setEditing(false);
                }}
                disabled={updateMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={updateMutation.isPending}
                onClick={() => updateMutation.mutate()}
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
              {canDeleteUser && (
                <Button
                  variant="secondary"
                  loading={deleteMutation.isPending}
                  onClick={() => setConfirmDelete(true)}
                  leadingIcon={<Icon icon={Trash2} size={14} />}
                >
                  Delete
                </Button>
              )}
              {canEditUser && (
                <Button
                  variant="primary"
                  onClick={() => setEditing(true)}
                  leadingIcon={<Icon icon={Pencil} size={14} />}
                >
                  Edit
                </Button>
              )}
            </>
          )
        )
      }
    >
      {!user ? (
        <div className="space-y-3">
          <Skeleton className="h-7 w-44" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : editing ? (
        <EditForm
          draft={draft}
          onChange={setDraft}
          allRoles={editableRoles}
          rolesPending={rolesQuery.isPending}
        />
      ) : (
        <div className="space-y-6">
          <Hero user={user} />
          <Facts user={user} />
          <RolesSection user={user} />
          {isSelf && (
            <Callout tone="info">
              This is your own account. The self-delete guard is enforced both
              client- and server-side.
            </Callout>
          )}
          {targetIsSuperAdmin && !meIsSuperuser && !isSelf && (
            <Callout tone="info" kicker="Restricted">
              Super-admin accounts can only be modified by another
              super-admin.
            </Callout>
          )}
        </div>
      )}
    </SlideOver>
    {user && (
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
        loading={deleteMutation.isPending}
        icon={Trash2}
        title="Delete this user?"
        confirmLabel="Delete user"
        cancelLabel="Keep user"
        message={
          <>
            <strong className="font-bold text-[var(--text-primary)]">
              {user.full_name || user.username}
            </strong>{" "}
            ({user.email}) loses access immediately and is removed from every
            role they hold. This cannot be undone. To suspend access without
            deleting, edit the user and clear the Active flag instead.
          </>
        }
      />
    )}
    </>
  );
}

function Hero({ user }: { user: User }) {
  const role = primaryRole(user) ?? "member";
  return (
    <section className="rounded-2xl bg-[var(--surface-soft)] p-5">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <RoleBadge role={role} />
        <StatusBadge
          icon={user.is_active ? CheckCircle2 : Ban}
          label={user.is_active ? "Active" : "Inactive"}
          tone={user.is_active ? "ok" : "muted"}
        />
        {user.is_verified && <StatusBadge icon={CheckCircle2} label="Verified" tone="info" />}
      </div>
      <div className="text-[22px] font-bold tabular leading-none text-[var(--text-primary)] tracking-[-0.01em]">
        {user.full_name || user.username}
      </div>
      <div className="mt-2 text-[12px] text-[var(--text-secondary)]">{user.email}</div>
    </section>
  );
}

function Facts({ user }: { user: User }) {
  return (
    <section>
      <div className="kicker mb-3">Facts</div>
      <div>
        <MetricRow label="Username" value={user.username} />
        <MetricRow label="Tenant" value={user.tenant_id} />
        <MetricRow
          label="Last Login"
          value={
            user.last_login_at
              ? `${formatRelativeTime(user.last_login_at)}${user.last_login_ip ? ` · ${user.last_login_ip}` : ""}`
              : "Never"
          }
        />
        <MetricRow label="Created" value={formatRelativeTime(user.created_at)} />
        <MetricRow label="Updated" value={formatRelativeTime(user.updated_at)} />
      </div>
    </section>
  );
}

function RolesSection({ user }: { user: User }) {
  return (
    <section>
      <div className="kicker mb-3">Assigned roles · {user.roles.length}</div>
      {user.roles.length === 0 ? (
        <div className="text-[12px] text-[var(--text-secondary)]">
          No role · falls back to member capabilities
        </div>
      ) : (
        <ul className="space-y-2">
          {user.roles.map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between rounded-xl bg-[var(--surface-soft)] px-3.5 py-2.5"
            >
              <span className="text-[13px] font-bold text-[var(--text-primary)]">
                {r.name}
              </span>
              {r.description && (
                <span className="text-[11px] text-[var(--text-secondary)] max-w-[60%] truncate">
                  {r.description}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function EditForm({
  draft,
  onChange,
  allRoles,
  rolesPending,
}: {
  draft: Draft;
  onChange: (next: Draft) => void;
  allRoles: { id: number; name: string; description: string | null }[];
  rolesPending: boolean;
}) {
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    onChange({ ...draft, [key]: value });

  const toggleRole = (roleId: number, checked: boolean) => {
    const next = checked
      ? Array.from(new Set([...draft.role_ids, roleId]))
      : draft.role_ids.filter((id) => id !== roleId);
    set("role_ids", next);
  };

  return (
    <div className="space-y-5">
      <Field id="ed-email" label="Email">
        <Input
          id="ed-email"
          type="email"
          autoComplete="email"
          value={draft.email}
          onChange={(e) => set("email", e.target.value)}
        />
      </Field>

      <Field id="ed-username" label="Username">
        <Input
          id="ed-username"
          autoComplete="username"
          value={draft.username}
          onChange={(e) => set("username", e.target.value)}
        />
      </Field>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field id="ed-first" label="First name">
          <Input
            id="ed-first"
            autoComplete="given-name"
            value={draft.first_name}
            onChange={(e) => set("first_name", e.target.value)}
          />
        </Field>

        <Field id="ed-last" label="Last name">
          <Input
            id="ed-last"
            autoComplete="family-name"
            value={draft.last_name}
            onChange={(e) => set("last_name", e.target.value)}
          />
        </Field>
      </div>

      <Field
        id="ed-password"
        label="Password"
        hint="Leave blank to keep the current credential."
      >
        <Input
          id="ed-password"
          type="password"
          autoComplete="new-password"
          value={draft.password}
          placeholder="••••••••"
          onChange={(e) => set("password", e.target.value)}
        />
      </Field>

      <label className="flex items-center gap-2.5 cursor-pointer">
        <Checkbox
          checked={draft.is_active}
          onChange={(e) => set("is_active", e.target.checked)}
        />
        <span className="text-[13px] text-[var(--text-primary)] font-medium">Active</span>
      </label>

      <div>
        <div className="kicker mb-2">Roles</div>
        {rolesPending ? (
          <Skeleton className="h-24 w-full" />
        ) : allRoles.length === 0 ? (
          <div className="text-[12px] text-[var(--text-secondary)]">No roles available</div>
        ) : (
          <ul className="space-y-2">
            {allRoles.map((r) => {
              const checked = draft.role_ids.includes(r.id);
              return (
                <li
                  key={r.id}
                  className="flex items-center gap-3 rounded-xl bg-[var(--surface-soft)] px-3.5 py-2.5"
                >
                  <Checkbox
                    aria-label={`role ${r.name}`}
                    checked={checked}
                    onChange={(e) => toggleRole(r.id, e.target.checked)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-bold text-[var(--text-primary)]">
                      {r.name}
                    </div>
                    {r.description && (
                      <div className="text-[11px] text-[var(--text-muted)] truncate">
                        {r.description}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

function Field({
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
        className="block text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--text-secondary)] mb-1.5"
      >
        {label}
      </label>
      {children}
      {hint && (
        <div className="mt-1.5 text-[11px] text-[var(--text-muted)]">{hint}</div>
      )}
    </div>
  );
}
