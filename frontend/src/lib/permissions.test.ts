import { describe, expect, it } from "vitest";
import {
  evaluatePermission,
  hasPermission,
  isSuperAdminUser,
  primaryRole,
} from "./permissions";
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
    last_login_at: null,
    last_login_ip: null,
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

  // F25 — the backend should always send a permissions object, but a
  // defensive null-guard keeps a malformed/null payload from throwing a
  // TypeError that would blank the whole app.
  it("does not throw when the user's permissions map is null", () => {
    const u = makeUser({
      permissions: null as unknown as Record<string, string[]>,
    });
    expect(() => hasPermission(u, "vms", "read")).not.toThrow();
    expect(hasPermission(u, "vms", "read")).toBe(false);
  });
});

// F24 — wildcard evaluation lived in two copies (`hasPermission` here and
// `permissionGranted` in api/roles.ts). Both now delegate to this single
// evaluator. These tests pin its contract directly.
describe("evaluatePermission — shared wildcard evaluator", () => {
  it("returns false for a null or undefined permissions map", () => {
    expect(evaluatePermission(null, "vms", "read")).toBe(false);
    expect(evaluatePermission(undefined, "vms", "read")).toBe(false);
  });

  it("matches the explicit action", () => {
    expect(evaluatePermission({ vms: ["read"] }, "vms", "read")).toBe(true);
    expect(evaluatePermission({ vms: ["read"] }, "vms", "delete")).toBe(false);
  });

  it("honors the '*' wildcard on the resource", () => {
    expect(evaluatePermission({ vms: ["*"] }, "vms", "delete")).toBe(true);
  });

  it("returns false for a resource absent from the map", () => {
    expect(evaluatePermission({ vms: ["read"] }, "roles", "read")).toBe(false);
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

describe("isSuperAdminUser", () => {
  it("returns false for a null user", () => {
    expect(isSuperAdminUser(null)).toBe(false);
  });

  it("returns true when the is_superuser flag is set", () => {
    expect(isSuperAdminUser(makeUser({ is_superuser: true }))).toBe(true);
  });

  it("returns true when the user carries the super_admin role", () => {
    const u = makeUser({ is_superuser: false, roles: [makeRole("super_admin")] });
    expect(isSuperAdminUser(u)).toBe(true);
  });

  it("returns false for an ordinary user without the flag or role", () => {
    expect(isSuperAdminUser(makeUser({ roles: [makeRole("admin")] }))).toBe(false);
  });
});
