import { api } from "@/lib/axios";
import { evaluatePermission } from "@/lib/permissions";

/**
 * Backend mirror of `VALID_ACTIONS`. Order is fixed so the matrix editor
 * always renders the same columns.
 */
export const ROLE_ACTIONS = ["create", "read", "update", "delete"] as const;
export type RoleAction = (typeof ROLE_ACTIONS)[number];

/** Wildcard "all actions" marker — sent to the API as a single-element list. */
export const ALL_ACTIONS = "*" as const;

export type RolePermissions = Record<string, string[]>;

/**
 * Roles returned by GET /api/v1/roles. Wider than the nested `Role` type in
 * `types.ts` — that one is the slice that ships inside user payloads.
 */
export type RoleDetail = {
  id: number;
  name: string;
  description: string | null;
  permissions: RolePermissions;
  is_active: boolean;
  is_system_role: boolean;
  created_at: string;
  updated_at: string;
};

export type RoleWithUsers = RoleDetail & {
  user_count: number;
};

export type RoleCount = {
  total: number;
  system_roles: number;
  custom_roles: number;
};

export type RoleResourcesResponse = {
  resources: string[];
  actions: string[];
  description: Record<string, string>;
};

export type ListRolesParams = {
  skip?: number;
  limit?: number;
  is_active?: boolean;
  search?: string;
};

export async function listRoles(params: ListRolesParams = {}): Promise<RoleDetail[]> {
  const res = await api.get<RoleDetail[]>("/roles", { params });
  return res.data;
}

export async function getRolesCount(
  params: { is_active?: boolean; search?: string } = {},
): Promise<RoleCount> {
  const res = await api.get<RoleCount>("/roles/count", { params });
  return res.data;
}

export async function getRole(id: number): Promise<RoleWithUsers> {
  const res = await api.get<RoleWithUsers>(`/roles/${id}`);
  return res.data;
}

export async function getRoleResources(): Promise<RoleResourcesResponse> {
  const res = await api.get<RoleResourcesResponse>("/roles/permissions/resources");
  return res.data;
}

export type CreateRolePayload = {
  name: string;
  description?: string | null;
  permissions: RolePermissions;
  is_active?: boolean;
};

export async function createRole(payload: CreateRolePayload): Promise<RoleDetail> {
  const res = await api.post<RoleDetail>("/roles", payload);
  return res.data;
}

export type UpdateRolePayload = {
  name?: string;
  description?: string | null;
  permissions?: RolePermissions;
  is_active?: boolean;
};

export async function updateRole(
  id: number,
  payload: UpdateRolePayload,
): Promise<RoleDetail> {
  const res = await api.put<RoleDetail>(`/roles/${id}`, payload);
  return res.data;
}

export async function deleteRole(id: number): Promise<void> {
  await api.delete(`/roles/${id}`);
}

/* ------------------------------- helpers --------------------------------- */

/**
 * Does the role grant the given (resource, action)? Delegates to the shared
 * `evaluatePermission` evaluator in `lib/permissions` — the wildcard rule
 * has a single implementation so the role-matrix editor and the user-facing
 * permission checks cannot diverge (F24).
 */
export function permissionGranted(
  permissions: RolePermissions,
  resource: string,
  action: RoleAction,
): boolean {
  return evaluatePermission(permissions, resource, action);
}

/** Does the role grant `*` on the resource (wildcard)? */
export function isWildcard(permissions: RolePermissions, resource: string): boolean {
  return permissions[resource]?.includes(ALL_ACTIONS) ?? false;
}
