import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, delay } from "msw";
import toast from "react-hot-toast";
import { server } from "@/test/msw/server";
import type { User } from "@/api/types";
import { api } from "./axios";
import { useAuthStore } from "@/store/auth";

// bootstrapAuth caches its promise at module-level to defend against
// React StrictMode double-mounting the AuthGate effect. Without the cache
// the second concurrent call hits the backend with the same refresh jti,
// which the family store classifies as token reuse and revokes the whole
// family — leaving the user logged out on the next reload. This suite
// pins that behavior.

describe("bootstrapAuth single-flight", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    server.resetHandlers();
  });

  it("dispatches a single /auth/refresh even on parallel calls", async () => {
    let refreshCalls = 0;
    server.use(
      http.post("/api/v1/auth/refresh", async () => {
        refreshCalls += 1;
        await delay(50);
        return HttpResponse.json({
          access_token: "rotated-token",
          token_type: "bearer",
          expires_in: 900,
        });
      }),
    );

    const { bootstrapAuth } = await import("./axios");
    const { useAuthStore } = await import("@/store/auth");
    useAuthStore.setState({ accessToken: null, user: null, bootstrapped: false });

    const [a, b] = await Promise.all([bootstrapAuth(), bootstrapAuth()]);

    expect(refreshCalls).toBe(1);
    expect(a).toBe(true);
    expect(b).toBe(true);
    expect(useAuthStore.getState().accessToken).toBe("rotated-token");
  });

  it("returns false and clears session when the refresh cookie is invalid", async () => {
    server.use(
      http.post("/api/v1/auth/refresh", () =>
        HttpResponse.json({ detail: "Refresh token invalide" }, { status: 401 }),
      ),
    );

    const { bootstrapAuth } = await import("./axios");
    const { useAuthStore } = await import("@/store/auth");
    useAuthStore.setState({
      accessToken: "stale-token",
      user: null,
      bootstrapped: false,
    });

    const result = await bootstrapAuth();

    expect(result).toBe(false);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("caches the result so a later call does not re-hit the network", async () => {
    let refreshCalls = 0;
    server.use(
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({
          access_token: "rotated-token",
          token_type: "bearer",
          expires_in: 900,
        });
      }),
    );

    const { bootstrapAuth } = await import("./axios");
    const { useAuthStore } = await import("@/store/auth");
    useAuthStore.setState({ accessToken: null, user: null, bootstrapped: false });

    await bootstrapAuth();
    await bootstrapAuth();
    await bootstrapAuth();

    expect(refreshCalls).toBe(1);
  });

  // F5 — a transient 5xx at startup must not cache a permanent failure.
  // The user would otherwise be frozen on /login until a full reload, even
  // once the backend recovers. A retryable failure resets the cached promise.
  it("does not cache a transient 5xx failure — a later call retries", async () => {
    let refreshCalls = 0;
    server.use(
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        // First call: backend briefly unavailable. Later: recovered.
        if (refreshCalls === 1) {
          return HttpResponse.json({ detail: "upstream down" }, { status: 503 });
        }
        return HttpResponse.json({
          access_token: "rotated-token",
          token_type: "bearer",
          expires_in: 900,
        });
      }),
    );

    const { bootstrapAuth } = await import("./axios");
    const { useAuthStore } = await import("@/store/auth");
    useAuthStore.setState({ accessToken: null, user: null, bootstrapped: false });

    const first = await bootstrapAuth();
    expect(first).toBe(false);

    // A second attempt (e.g. the user reloads or a retry timer fires) must
    // re-hit the network now that the cached failure has been cleared.
    const second = await bootstrapAuth();
    expect(second).toBe(true);
    expect(refreshCalls).toBe(2);
  });

  // A genuine 401 (invalid/absent refresh cookie) is a definitive answer —
  // the result stays cached so we do not hammer /auth/refresh on every render.
  it("caches a 401 (definitive unauthenticated) — no retry", async () => {
    let refreshCalls = 0;
    server.use(
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({ detail: "Refresh invalide" }, { status: 401 });
      }),
    );

    const { bootstrapAuth } = await import("./axios");
    const { useAuthStore } = await import("@/store/auth");
    useAuthStore.setState({ accessToken: null, user: null, bootstrapped: false });

    await bootstrapAuth();
    await bootstrapAuth();

    expect(refreshCalls).toBe(1);
  });
});

// F7 — REFRESH_EXEMPT_PATHS must match by exact path, not substring.
// `url.includes("/auth/login")` would also exempt a hypothetical
// `/auth/login-history` endpoint from the 401-refresh flow.
describe("isRefreshExempt — exact path matching", () => {
  afterEach(() => {
    server.resetHandlers();
  });

  it("does NOT exempt a path that merely contains an exempt path as a substring", async () => {
    // A 401 on a non-exempt endpoint must trigger the refresh flow.
    let refreshCalls = 0;
    let secondCall = false;
    server.use(
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({
          access_token: "rotated",
          token_type: "bearer",
          expires_in: 900,
        });
      }),
      // `/auth/login-attempts` contains "/auth/login" as a substring but is
      // a distinct, protected endpoint — a 401 here must NOT be exempt.
      http.get("/api/v1/auth/login-attempts", () => {
        if (secondCall) return HttpResponse.json({ ok: true });
        secondCall = true;
        return HttpResponse.json({ detail: "stale token" }, { status: 401 });
      }),
    );

    const { api } = await import("./axios");
    const { useAuthStore } = await import("@/store/auth");
    useAuthStore.setState({
      accessToken: "stale",
      user: null,
      bootstrapped: true,
    });

    const res = await api.get("/auth/login-attempts");
    // The interceptor refreshed and replayed — proof the path was NOT exempt.
    expect(refreshCalls).toBe(1);
    expect(res.data).toEqual({ ok: true });
  });
});

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

describe("axios — account-deactivation handling", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: fakeUser,
      accessToken: "fake-access",
      bootstrapped: true,
    });
    vi.spyOn(toast, "error").mockImplementation(() => "toast-id");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    server.resetHandlers();
  });

  it("clears the session and notifies on a deactivated-account 403", async () => {
    server.use(
      http.get("/api/v1/vms", () =>
        HttpResponse.json(
          { detail: "Compte utilisateur inactif" },
          { status: 403, headers: { "X-Account-Status": "deactivated" } },
        ),
      ),
    );

    await expect(api.get("/vms")).rejects.toBeDefined();

    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("deactivated"),
      expect.objectContaining({ id: "account-deactivated" }),
    );
  });

  it("leaves the session intact on an ordinary permission-denied 403", async () => {
    server.use(
      http.get("/api/v1/vms", () =>
        HttpResponse.json(
          { detail: "Permission manquante : vms:read" },
          { status: 403 },
        ),
      ),
    );

    await expect(api.get("/vms")).rejects.toBeDefined();

    expect(useAuthStore.getState().user).not.toBeNull();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
