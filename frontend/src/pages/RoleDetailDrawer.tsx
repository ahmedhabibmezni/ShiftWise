import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Lock, Pencil, Save, Trash2, Users as UsersIcon } from "lucide-react";
import toast from "react-hot-toast";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { MetricRow } from "@/components/ui/MetricRow";
import { PermissionsMatrix } from "@/components/ui/PermissionsMatrix";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
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
import type { ApiError } from "@/api/types";

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

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

  // Reset the draft whenever the drawer closes / opens / loads a new role.
  // Editing a custom role is opt-in via the Edit button; system roles can
  // never enter edit mode.
  useEffect(() => {
    if (!detailQuery.data) return;
    setDraftName(detailQuery.data.name);
    setDraftDescription(detailQuery.data.description ?? "");
    setDraftPermissions(detailQuery.data.permissions ?? {});
    setDraftActive(detailQuery.data.is_active);
  }, [detailQuery.data]);

  useEffect(() => {
    if (!open) setEditing(false);
  }, [open]);

  const updateMutation = useMutation({
    mutationFn: () =>
      updateRole(id!, {
        name: draftName,
        description: draftDescription || null,
        permissions: draftPermissions,
        is_active: draftActive,
      }),
    onSuccess: () => {
      toast.success("role updated");
      queryClient.invalidateQueries({ queryKey: ["role", id] });
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      setEditing(false);
    },
    onError: (err) => toast.error(describeError(err, "update failed")),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRole(id!),
    onSuccess: () => {
      toast.success("role deleted");
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      onClose();
    },
    onError: (err) => toast.error(describeError(err, "delete failed")),
  });

  const role = detailQuery.data;
  const isSystem = role?.is_system_role ?? false;
  const editable = canUpdate && !isSystem;
  const deletable = canDelete && !isSystem && (role?.user_count ?? 0) === 0;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title={role ? role.name : "role"}
      footer={
        role && (
          <>
            <Button variant="secondary" onClick={onClose}>
              close
            </Button>
            {editing ? (
              <Button
                variant="primary"
                uppercase
                loading={updateMutation.isPending}
                onClick={() => updateMutation.mutate()}
                leadingIcon={<Icon icon={Save} size={14} />}
              >
                save
              </Button>
            ) : (
              <>
                {deletable && (
                  <Button
                    variant="secondary"
                    uppercase
                    loading={deleteMutation.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `delete role '${role.name}'? this cannot be undone.`,
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
                {editable && (
                  <Button
                    variant="primary"
                    uppercase
                    onClick={() => setEditing(true)}
                    leadingIcon={<Icon icon={Pencil} size={14} />}
                  >
                    edit
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
            <div className="kicker mb-2">permissions matrix</div>
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
              system role · permissions are seeded at install and cannot be changed.
            </Callout>
          )}

          {!isSystem && role.user_count > 0 && !editing && (
            <Callout tone="warn">
              <div className="font-mono text-[11px]">
                <span className="kicker mr-2">in use</span>
                this role is assigned to {role.user_count} user
                {role.user_count > 1 ? "s" : ""}. Deletion requires unassigning
                them first.
              </div>
            </Callout>
          )}
        </div>
      )}
    </SlideOver>
  );
}

function Hero({
  role,
}: {
  role: { name: string; is_system_role: boolean; is_active: boolean; user_count: number };
}) {
  return (
    <section className="border border-line bg-bg-elev p-5">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Badge variant={role.is_system_role ? "info" : "ok"}>
          {role.is_system_role ? "system" : "custom"}
        </Badge>
        <Badge variant={role.is_active ? "ok" : "neutral"}>
          {role.is_active ? "active" : "disabled"}
        </Badge>
      </div>
      <div className="font-mono tabular text-[22px] leading-none text-ink">
        {role.name}
      </div>
      <div className="mt-3 flex items-center gap-2 font-mono text-[11px] text-ink-muted">
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
      <div className="kicker mb-3">facts</div>
      <div>
        <MetricRow label="description" value={description ?? "—"} />
        <MetricRow label="users" value={`${userCount}`} />
        <MetricRow label="created" value={formatRelativeTime(createdAt)} />
        <MetricRow label="updated" value={formatRelativeTime(updatedAt)} />
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
        <label className="block kicker mb-1.5" htmlFor="role-name">
          name
        </label>
        <Input
          id="role-name"
          value={name}
          onChange={(e) => onName(e.target.value)}
        />
      </div>
      <div>
        <label className="block kicker mb-1.5" htmlFor="role-desc">
          description
        </label>
        <Textarea
          id="role-desc"
          rows={2}
          value={description}
          onChange={(e) => onDescription(e.target.value)}
        />
      </div>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 accent-signal"
          checked={active}
          onChange={(e) => onActive(e.target.checked)}
        />
        <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
          active
        </span>
      </label>
    </section>
  );
}
