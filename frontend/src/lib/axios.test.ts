import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse, delay } from "msw";
import { server } from "@/test/msw/server";

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
});
