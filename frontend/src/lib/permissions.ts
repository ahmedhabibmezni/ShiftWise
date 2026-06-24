import type { User } from "@/api/types";
import { useAuthStore } from "@/store/auth";

export type ResourceAction = "read" | "create" | "update" | "delete";

export const SUPER_ADMIN_ROLE = "super_admin";

/** Wildcard marker — an entry of `"*"` on a resource grants every action. */
export const WILDCARD_ACTION = "*";

export const ROLE_ORDER = ["super_admin", "admin", "user", "viewer"] as const;
export type RoleName = (typeof ROLE_ORDER)[number] | (string & {});

/** A `resource -> actions` permission map, as carried by users and roles. */
export type PermissionMap = Record<string, string[]>;

/**
 * Single source of truth for "does this permission map grant
 * `resource:action`?" — the wildcard rule (`"*"` ⇒ all actions) lived in
 * two hand-rolled copies (`hasPermission` and `api/roles.ts`'
 * `permissionGranted`); both now delegate here so the rule cannot drift.
 *
 * Tolerates a `null`/`undefined` map (F25): the backend should always send
 * one, but a malformed payload must not throw a `TypeError` that blanks the
 * UI. A missing map simply grants nothing.
 *
 * Frontend permission checks are a UX affordance only — the backend RBAC
 * layer is the real gate. This keeps the displayed buttons consistent with
 * what the server will actually allow.
 */
export function evaluatePermission(
  permissions: PermissionMap | null | undefined,
  resource: string,
  action: ResourceAction,
): boolean {
  const actions = permissions?.[resource];
  if (!actions) return false;
  return actions.includes(WILDCARD_ACTION) || actions.includes(action);
}

export function hasPermission(
  user: User | null,
  resource: string,
  action: ResourceAction,
): boolean {
  if (!user) return false;
  if (user.is_superuser) return true;
  // `user.permissions` is typed non-nullable, but evaluatePermission
  // null-guards it anyway in case the backend returns a malformed payload.
  return evaluatePermission(user.permissions, resource, action);
}

/**
 * Pick the highest-privilege role assigned to the user. Super-users are
 * always reported as `super_admin` even when the DB row carries other roles.
 */
export function primaryRole(user: User | null): RoleName | null {
  if (!user) return null;
  if (user.is_superuser) return "super_admin";
  const names = user.roles.map((r) => r.name);
  for (const r of ROLE_ORDER) if (names.includes(r)) return r;
  return names[0] ?? null;
}

export function useHasPermission(
  resource: string,
  action: ResourceAction,
): boolean {
  const user = useAuthStore((s) => s.user);
  return hasPermission(user, resource, action);
}

/**
 * True when the user holds super-admin privileges — either the
 * `is_superuser` flag or the `super_admin` role. Such accounts may only
 * be created, edited or deleted by another super-admin; the backend
 * enforces the same rule server-side.
 */
export function isSuperAdminUser(user: User | null): boolean {
  if (!user) return false;
  if (user.is_superuser) return true;
  return user.roles.some((r) => r.name === SUPER_ADMIN_ROLE);
}

export function usePrimaryRole(): RoleName | null {
  const user = useAuthStore((s) => s.user);
  return primaryRole(user);
}
