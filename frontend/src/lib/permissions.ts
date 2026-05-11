import type { User } from "@/api/types";
import { useAuthStore } from "@/store/auth";

export type ResourceAction = "read" | "create" | "update" | "delete";

export const ROLE_ORDER = ["super_admin", "admin", "user", "viewer"] as const;
export type RoleName = (typeof ROLE_ORDER)[number] | (string & {});

export function hasPermission(
  user: User | null,
  resource: string,
  action: ResourceAction,
): boolean {
  if (!user) return false;
  if (user.is_superuser) return true;
  const perms = user.permissions[resource];
  if (!perms) return false;
  return perms.includes("*") || perms.includes(action);
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

export function usePrimaryRole(): RoleName | null {
  const user = useAuthStore((s) => s.user);
  return primaryRole(user);
}
