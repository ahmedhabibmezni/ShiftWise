import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/store/auth";
import { queryClient } from "@/lib/queryClient";
import { forceLogout, registerSessionNavigator } from "@/lib/session";
import type { User } from "@/api/types";

const fakeUser: User = {
  id: 1,
  email: "op@shiftwise.local",
  username: "op",
  first_name: null,
  last_name: null,
  full_name: "op",
  tenant_id: "t1",
  is_active: true,
  is_verified: true,
  is_superuser: false,
  last_login_at: null,
  last_login_ip: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  roles: [],
  permissions: { vms: ["read"] },
};

describe("forceLogout — centralized session teardown", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: fakeUser,
      accessToken: "fake-access",
      bootstrapped: true,
    });
    queryClient.clear();
  });

  afterEach(() => {
    registerSessionNavigator(() => {});
  });

  it("clears the auth store (token + user)", () => {
    registerSessionNavigator(() => {});
    forceLogout();
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("purges the TanStack Query cache so prior-tenant data cannot leak", () => {
    // Seed a query result as if the previous tenant's data was cached.
    queryClient.setQueryData(["stats", "vms"], { total: 999 });
    expect(queryClient.getQueryData(["stats", "vms"])).toBeDefined();

    registerSessionNavigator(() => {});
    forceLogout();

    expect(queryClient.getQueryData(["stats", "vms"])).toBeUndefined();
  });

  it("imperatively navigates to /login", () => {
    const navigate = vi.fn();
    registerSessionNavigator(navigate);
    forceLogout();
    expect(navigate).toHaveBeenCalledWith("/login");
  });

  it("is safe to call when no navigator is registered", () => {
    registerSessionNavigator(undefined as unknown as (p: string) => void);
    // Should not throw even without a navigator.
    expect(() => forceLogout()).not.toThrow();
  });
});
