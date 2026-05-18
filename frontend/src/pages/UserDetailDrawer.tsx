import { useMemo, useState } from "react";
import { Controller, useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import type { User } from "@/api/types";
import { describeError } from "@/lib/errors";
import { formatRelativeTime } from "@/lib/format";
import {
  isSuperAdminUser,
  primaryRole,
  SUPER_ADMIN_ROLE,
  useHasPermission,
} from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";
import { userEditSchema, type UserEditValues } from "./userForm";

const USER_EDIT_FORM_ID = "user-edit-form";

/** Seed react-hook-form's default values from the loaded user. */
function editValuesFrom(u: User): UserEditValues {
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

function diffPayload(u: User, values: UserEditValues): UpdateUserPayload {
  // Ship only what actually changed — same rationale as the hypervisor diff:
  // partial updates avoid clobbering unknown fields, and the password is
  // forbidden as an empty string by the backend's min_length validator.
  const payload: UpdateUserPayload = {};
  if (values.email !== u.email) payload.email = values.email;
  if (values.username !== u.username) payload.username = values.username;
  const nextFirst = values.first_name ?? "";
  if (nextFirst !== (u.first_name ?? "")) {
    payload.first_name = nextFirst || null;
  }
  const nextLast = values.last_name ?? "";
  if (nextLast !== (u.last_name ?? "")) {
    payload.last_name = nextLast || null;
  }
  if (values.password.length > 0) payload.password = values.password;
  if (values.is_active !== u.is_active) payload.is_active = values.is_active;
  const currentIds = u.roles.map((r) => r.id).sort();
  const nextIds = [...values.role_ids].sort();
  if (JSON.stringify(currentIds) !== JSON.stringify(nextIds)) {
    payload.role_ids = values.role_ids;
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
  const open = id !== null;
  const canUpdate = useHasPermission("users", "update");
  const canDelete = useHasPermission("users", "delete");
  const me = useAuthStore((s) => s.user);
  const isSelf = !!me && me.id === id;
  const meIsSuperuser = me?.is_superuser ?? false;
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Mirrors the EditForm child's in-flight update state so the footer
  // Save button (rendered outside that form) can show its spinner.
  const [savePending, setSavePending] = useState(false);
  const queryClient = useQueryClient();

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
                onClick={() => setEditing(false)}
                disabled={savePending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                form={USER_EDIT_FORM_ID}
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
          user={user}
          allRoles={editableRoles}
          rolesPending={rolesQuery.isPending}
          isSelf={isSelf}
          onSavingChange={setSavePending}
          onSaved={() => setEditing(false)}
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

/**
 * User edit form — react-hook-form + Zod (`userEditSchema`), the same
 * validated pipeline as the create drawer. Previously this was a raw
 * `useState` draft with no inline errors (F9).
 *
 * The form owns its update mutation; the Save button lives in the drawer
 * footer and submits via `form={USER_EDIT_FORM_ID}`. `onSavingChange` keeps
 * that out-of-form button's spinner in sync.
 */
function EditForm({
  user,
  allRoles,
  rolesPending,
  isSelf,
  onSavingChange,
  onSaved,
}: {
  user: User;
  allRoles: { id: number; name: string; description: string | null }[];
  rolesPending: boolean;
  isSelf: boolean;
  onSavingChange: (saving: boolean) => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const setAuthUser = useAuthStore((s) => s.setUser);
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<UserEditValues>({
    resolver: zodResolver(userEditSchema),
    defaultValues: editValuesFrom(user),
  });

  const updateMutation = useMutation({
    mutationFn: (values: UserEditValues) => {
      const payload = diffPayload(user, values);
      if (Object.keys(payload).length === 0) {
        return Promise.resolve(user);
      }
      return updateUser(user.id, payload);
    },
    onMutate: () => onSavingChange(true),
    onSuccess: (next) => {
      toast.success("User updated");
      queryClient.invalidateQueries({ queryKey: ["user", user.id] });
      queryClient.invalidateQueries({ queryKey: ["users"] });
      // If the operator just edited their own profile, push the new user
      // object straight into the auth store. /me is read once by AuthGate
      // at boot — there's no React Query for it — so invalidating a
      // synthetic "auth/me" key wouldn't actually refresh anything. The
      // sidebar and route guards all read from the store.
      if (isSelf) {
        setAuthUser(next);
      }
      onSaved();
    },
    onError: (err) => toast.error(describeError(err, "Update failed")),
    onSettled: () => onSavingChange(false),
  });

  const onSubmit: SubmitHandler<UserEditValues> = (values) =>
    updateMutation.mutate(values);

  return (
    <form
      id={USER_EDIT_FORM_ID}
      onSubmit={handleSubmit(onSubmit)}
      noValidate
      className="space-y-5"
    >
      <Field id="ed-email" label="Email" error={errors.email?.message}>
        <Input
          id="ed-email"
          type="email"
          autoComplete="email"
          invalid={!!errors.email}
          {...register("email")}
        />
      </Field>

      <Field id="ed-username" label="Username" error={errors.username?.message}>
        <Input
          id="ed-username"
          autoComplete="username"
          invalid={!!errors.username}
          {...register("username")}
        />
      </Field>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field id="ed-first" label="First name" error={errors.first_name?.message}>
          <Input
            id="ed-first"
            autoComplete="given-name"
            invalid={!!errors.first_name}
            {...register("first_name")}
          />
        </Field>

        <Field id="ed-last" label="Last name" error={errors.last_name?.message}>
          <Input
            id="ed-last"
            autoComplete="family-name"
            invalid={!!errors.last_name}
            {...register("last_name")}
          />
        </Field>
      </div>

      <Field
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
      </Field>

      <label className="flex items-center gap-2.5 cursor-pointer">
        <Checkbox {...register("is_active")} />
        <span className="text-[13px] text-[var(--text-primary)] font-medium">Active</span>
      </label>

      {/* role_ids is a number[]; a Controller bridges the checkbox list to
          react-hook-form so it is validated and submitted with the rest. */}
      <Controller
        control={control}
        name="role_ids"
        render={({ field }) => (
          <div>
            <div className="kicker mb-2">Roles</div>
            {rolesPending ? (
              <Skeleton className="h-24 w-full" />
            ) : allRoles.length === 0 ? (
              <div className="text-[12px] text-[var(--text-secondary)]">
                No roles available
              </div>
            ) : (
              <ul className="space-y-2">
                {allRoles.map((r) => {
                  const checked = field.value.includes(r.id);
                  return (
                    <li
                      key={r.id}
                      className="flex items-center gap-3 rounded-xl bg-[var(--surface-soft)] px-3.5 py-2.5"
                    >
                      <Checkbox
                        aria-label={`role ${r.name}`}
                        checked={checked}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? Array.from(new Set([...field.value, r.id]))
                            : field.value.filter((id) => id !== r.id);
                          field.onChange(next);
                        }}
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
        )}
      />
    </form>
  );
}

function Field({
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
