import { describe, expect, it } from "vitest";
import { hasPermission, primaryRole } from "./permissions";
import type { Role, User } from "@/api/types";

function makeRole(name: string): Role {
  return {
    id: 1,
    name,
    description: null,
    is_system_role: true,
    permissions: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function makeUser(over: Partial<User> = {}): User {
  return {
    id: 1,
    email: "u@shiftwise.local",
    username: "u",
    first_name: null,
    last_name: null,
    full_name: "U",
    tenant_id: "t1",
    is_active: true,
    is_verified: true,
    is_superuser: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    roles: [],
    permissions: {},
    ...over,
  };
}

describe("hasPermission", () => {
  it("returns false for a null user", () => {
    expect(hasPermission(null, "users", "read")).toBe(false);
  });

  it("grants every action to a super-user regardless of permission map", () => {
    const su = makeUser({ is_superuser: true, permissions: {} });
    expect(hasPermission(su, "users", "delete")).toBe(true);
    expect(hasPermission(su, "anything", "read")).toBe(true);
  });

  it("honors the wildcard '*' on a resource", () => {
    const u = makeUser({ permissions: { hypervisors: ["*"] } });
    expect(hasPermission(u, "hypervisors", "create")).toBe(true);
    expect(hasPermission(u, "hypervisors", "delete")).toBe(true);
  });

  it("matches explicit actions", () => {
    const u = makeUser({ permissions: { users: ["read"] } });
    expect(hasPermission(u, "users", "read")).toBe(true);
    expect(hasPermission(u, "users", "create")).toBe(false);
  });

  it("rejects resources missing from the map", () => {
    const u = makeUser({ permissions: { vms: ["read"] } });
    expect(hasPermission(u, "hypervisors", "read")).toBe(false);
  });
});

describe("primaryRole", () => {
  it("returns null for an anonymous user", () => {
    expect(primaryRole(null)).toBeNull();
  });

  it("always returns super_admin for super-users", () => {
    const su = makeUser({
      is_superuser: true,
      roles: [makeRole("viewer")],
    });
    expect(primaryRole(su)).toBe("super_admin");
  });

  it("picks the highest-privilege role in the standard order", () => {
    const u = makeUser({
      roles: [makeRole("viewer"), makeRole("admin"), makeRole("user")],
    });
    expect(primaryRole(u)).toBe("admin");
  });

  it("falls back to the first role when none is in the standard set", () => {
    const u = makeUser({ roles: [makeRole("custom-op")] });
    expect(primaryRole(u)).toBe("custom-op");
  });
});
