import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, Lock, Pencil, Save, Trash2, Users as UsersIcon } from "lucide-react";
import toast from "react-hot-toast";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Checkbox } from "@/components/ui/Checkbox";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { MetricRow } from "@/components/ui/MetricRow";
import { PermissionsMatrix } from "@/components/ui/PermissionsMatrix";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Textarea } from "@/components/ui/Textarea";
import {
  deleteRole,
  getRole,
  getRoleResources,
  updateRole,
  type RolePermissions,
} from "@/api/roles";
import { useHasPermission } from "@/lib/permissions";
import { formatRelativeTime } from "@/lib/format";
import { describeError } from "@/lib/errors";

export function RoleDetailDrawer({
  id,
  onClose,
}: {
  id: number | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = id !== null;
  const canUpdate = useHasPermission("roles", "update");
  const canDelete = useHasPermission("roles", "delete");
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [draftPermissions, setDraftPermissions] = useState<RolePermissions>({});
  const [draftActive, setDraftActive] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["role", id],
    queryFn: () => getRole(id!),
    enabled: open,
  });

  const resourcesQuery = useQuery({
    queryKey: ["roles", "resources"],
    queryFn: getRoleResources,
    enabled: open,
    staleTime: 60 * 60_000,
  });

  // Seed the draft from the loaded role and enter edit mode. Done in the
  // click handler (not an effect) so the draft is always a fresh snapshot
  // of the server state at the moment editing begins. The parent remounts
  // this drawer via a `key` per selected id, so no close-time reset is
  // needed — `editing`/`confirmDelete` start false on every open.
  const enterEditMode = () => {
    const data = detailQuery.data;
    if (!data) return;
    setDraftName(data.name);
    setDraftDescription(data.description ?? "");
    setDraftPermissions(data.permissions ?? {});
    setDraftActive(data.is_active);
    setEditing(true);
  };

  const updateMutation = useMutation({
    mutationFn: () =>
      updateRole(id!, {
        name: draftName,
        description: draftDescription || null,
        permissions: draftPermissions,
        is_active: draftActive,
      }),
    onSuccess: () => {
      toast.success("Role updated");
      queryClient.invalidateQueries({ queryKey: ["role", id] });
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      setEditing(false);
    },
    onError: (err) => toast.error(describeError(err, "Update failed")),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRole(id!),
    onSuccess: () => {
      toast.success("Role deleted");
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      onClose();
    },
    onError: (err) => {
      setConfirmDelete(false);
      toast.error(describeError(err, "Delete failed"));
    },
  });

  const role = detailQuery.data;
  const isSystem = role?.is_system_role ?? false;
  const editable = canUpdate && !isSystem;
  const deletable = canDelete && !isSystem && (role?.user_count ?? 0) === 0;

  return (
    <>
    <SlideOver
      open={open}
      onClose={onClose}
      title={role ? role.name : "Role"}
      footer={
        role && (
          <>
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
            {editing ? (
              <Button
                variant="primary"
                loading={updateMutation.isPending}
                onClick={() => updateMutation.mutate()}
                leadingIcon={<Icon icon={Save} size={14} />}
              >
                Save
              </Button>
            ) : (
              <>
                {deletable && (
                  <Button
                    variant="secondary"
                    loading={deleteMutation.isPending}
                    onClick={() => setConfirmDelete(true)}
                    leadingIcon={<Icon icon={Trash2} size={14} />}
                  >
                    Delete
                  </Button>
                )}
                {editable && (
                  <Button
                    variant="primary"
                    onClick={enterEditMode}
                    leadingIcon={<Icon icon={Pencil} size={14} />}
                  >
                    Edit
                  </Button>
                )}
              </>
            )}
          </>
        )
      }
    >
      {!role ? (
        <div className="space-y-3">
          <Skeleton className="h-7 w-44" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : (
        <div className="space-y-6">
          <Hero role={role} />

          {editing ? (
            <EditFields
              name={draftName}
              onName={setDraftName}
              description={draftDescription}
              onDescription={setDraftDescription}
              active={draftActive}
              onActive={setDraftActive}
            />
          ) : (
            <Facts
              userCount={role.user_count}
              description={role.description}
              createdAt={role.created_at}
              updatedAt={role.updated_at}
            />
          )}

          <section>
            <div className="kicker mb-2">Permissions matrix</div>
            {resourcesQuery.data ? (
              <PermissionsMatrix
                resources={resourcesQuery.data.resources}
                permissions={editing ? draftPermissions : role.permissions}
                onChange={editing ? setDraftPermissions : undefined}
                describeResource={(r) => resourcesQuery.data.description[r]}
                disabled={!editing}
              />
            ) : (
              <Skeleton className="h-48 w-full" />
            )}
          </section>

          {isSystem && (
            <Callout tone="info" icon={Lock}>
              System role · permissions are seeded at install and cannot be changed.
            </Callout>
          )}

          {!isSystem && role.user_count > 0 && !editing && (
            <Callout tone="warn" kicker="In use">
              This role is assigned to {role.user_count} user
              {role.user_count > 1 ? "s" : ""}. Deletion requires unassigning
              them first.
            </Callout>
          )}
        </div>
      )}
    </SlideOver>
    {role && (
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
        loading={deleteMutation.isPending}
        icon={Trash2}
        title="Delete this role?"
        confirmLabel="Delete role"
        cancelLabel="Keep role"
        message={
          <>
            The custom role{" "}
            <strong className="font-bold text-[var(--text-primary)]">
              {role.name}
            </strong>{" "}
            and its permission set are removed. No users are assigned to it, so
            no access changes for anyone. This cannot be undone.
          </>
        }
      />
    )}
    </>
  );
}

function Hero({
  role,
}: {
  role: { name: string; is_system_role: boolean; is_active: boolean; user_count: number };
}) {
  return (
    <section className="rounded-2xl bg-[var(--surface-soft)] p-5">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <StatusBadge
          icon={Lock}
          label={role.is_system_role ? "System" : "Custom"}
          tone={role.is_system_role ? "info" : "muted"}
        />
        <StatusBadge
          icon={role.is_active ? CheckCircle2 : Ban}
          label={role.is_active ? "Active" : "Disabled"}
          tone={role.is_active ? "ok" : "muted"}
        />
      </div>
      <div className="text-[22px] font-bold tabular leading-none text-[var(--text-primary)] tracking-[-0.01em]">
        {role.name}
      </div>
      <div className="mt-3 flex items-center gap-2 text-[12px] text-[var(--text-secondary)]">
        <Icon icon={UsersIcon} size={12} />
        {role.user_count} user{role.user_count !== 1 ? "s" : ""} assigned
      </div>
    </section>
  );
}

function Facts({
  userCount,
  description,
  createdAt,
  updatedAt,
}: {
  userCount: number;
  description: string | null;
  createdAt: string;
  updatedAt: string;
}) {
  return (
    <section>
      <div className="kicker mb-3">Facts</div>
      <div>
        <MetricRow label="Description" value={description ?? "—"} />
        <MetricRow label="Users" value={`${userCount}`} />
        <MetricRow label="Created" value={formatRelativeTime(createdAt)} />
        <MetricRow label="Updated" value={formatRelativeTime(updatedAt)} />
      </div>
    </section>
  );
}

function EditFields({
  name,
  onName,
  description,
  onDescription,
  active,
  onActive,
}: {
  name: string;
  onName: (v: string) => void;
  description: string;
  onDescription: (v: string) => void;
  active: boolean;
  onActive: (v: boolean) => void;
}) {
  return (
    <section className="space-y-4">
      <div>
        <label
          className="block text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--text-secondary)] mb-1.5"
          htmlFor="role-name"
        >
          Name
        </label>
        <Input id="role-name" value={name} onChange={(e) => onName(e.target.value)} />
      </div>
      <div>
        <label
          className="block text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--text-secondary)] mb-1.5"
          htmlFor="role-desc"
        >
          Description
        </label>
        <Textarea
          id="role-desc"
          rows={2}
          value={description}
          onChange={(e) => onDescription(e.target.value)}
        />
      </div>
      <label className="flex items-center gap-2.5 cursor-pointer">
        <Checkbox checked={active} onChange={(e) => onActive(e.target.checked)} />
        <span className="text-[13px] text-[var(--text-primary)] font-medium">Active</span>
      </label>
    </section>
  );
}
