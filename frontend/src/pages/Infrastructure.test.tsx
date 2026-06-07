import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import type { User } from "@/api/types";
import type { ClusterConfigRead, ClusterConfigScopeEntry } from "@/api/infrastructure";
import { useAuthStore } from "@/store/auth";
import Infrastructure from "./Infrastructure";

function makeUser(over: Partial<User> = {}): User {
  return {
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
    permissions: { infrastructure: ["read", "update"] },
    ...over,
  };
}

function makeConfig(over: Partial<ClusterConfigRead> = {}): ClusterConfigRead {
  return {
    scope_type: "platform_default",
    tenant_id: null,
    mode: "custom",
    has_credentials: true,
    api_url: "https://api.example.com:6443",
    verify_ssl: false,
    default_namespace: "default",
    health_status: "healthy",
    health_reason: "cluster reachable",
    health_checked_at: "2026-06-07T00:00:00Z",
    config_version: 3,
    updated_at: "2026-06-07T00:00:00Z",
    updated_by_user_id: 1,
    ...over,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/infrastructure"]}>
        <Infrastructure />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Infrastructure page", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: makeUser({ is_superuser: true }) });
  });

  it("superuser sees the scope selector with platform default", async () => {
    const tenantEntry: ClusterConfigScopeEntry = {
      scope_type: "tenant",
      tenant_id: "acme",
      using_platform_default: false,
      config: makeConfig({ scope_type: "tenant", tenant_id: "acme" }),
    };
    server.use(
      http.get("/api/v1/infrastructure/scopes", () =>
        HttpResponse.json({
          items: [
            { scope_type: "platform_default", tenant_id: null, using_platform_default: false, config: makeConfig() },
            tenantEntry,
          ],
        }),
      ),
      http.get("/api/v1/infrastructure/platform-default", () =>
        HttpResponse.json({
          scope_type: "platform_default",
          tenant_id: null,
          using_platform_default: false,
          config: makeConfig(),
        }),
      ),
    );

    renderPage();

    await screen.findByRole("heading", { name: "Infrastructure" });
    // Scope select offers platform default + the configured tenant.
    await screen.findByRole("option", { name: "Platform default" });
    await screen.findByRole("option", { name: "Tenant: acme" });
  });

  it("shows the healthy badge from the live status", async () => {
    server.use(
      http.get("/api/v1/infrastructure/scopes", () =>
        HttpResponse.json({ items: [] }),
      ),
      http.get("/api/v1/infrastructure/platform-default", () =>
        HttpResponse.json({
          scope_type: "platform_default",
          tenant_id: null,
          using_platform_default: false,
          config: makeConfig({ health_status: "healthy" }),
        }),
      ),
    );

    renderPage();
    await waitFor(() => expect(screen.getByText(/healthy/i)).toBeInTheDocument());
  });

  it("surfaces a structured error when saving fails", async () => {
    server.use(
      http.get("/api/v1/infrastructure/scopes", () => HttpResponse.json({ items: [] })),
      http.get("/api/v1/infrastructure/platform-default", () =>
        HttpResponse.json({
          scope_type: "platform_default",
          tenant_id: null,
          using_platform_default: false,
          config: makeConfig({ mode: "custom" }),
        }),
      ),
      http.put("/api/v1/infrastructure/platform-default", () =>
        HttpResponse.json(
          { detail: { code: "ERR_INVALID_HOST", message: "host forbidden" } },
          { status: 422 },
        ),
      ),
    );

    renderPage();
    const saveBtn = await screen.findByRole("button", { name: /save configuration/i });
    await userEvent.click(saveBtn);
    await waitFor(() => expect(screen.getByText("host forbidden")).toBeInTheDocument());
  });

  it("tenant admin is locked to their own scope (no platform default option)", async () => {
    useAuthStore.setState({ user: makeUser({ is_superuser: false, tenant_id: "acme" }) });
    server.use(
      http.get("/api/v1/infrastructure/scopes", () =>
        HttpResponse.json({
          items: [
            { scope_type: "tenant", tenant_id: "acme", using_platform_default: true, config: null },
          ],
        }),
      ),
      http.get("/api/v1/infrastructure/tenant:acme", () =>
        HttpResponse.json({
          scope_type: "tenant",
          tenant_id: "acme",
          using_platform_default: true,
          config: null,
        }),
      ),
    );

    renderPage();
    await screen.findByRole("heading", { name: "Infrastructure" });
    // No platform-default option for a tenant admin.
    expect(screen.queryByRole("option", { name: "Platform default" })).toBeNull();
    // in-cluster is not offered for a tenant scope.
    await waitFor(() =>
      expect(screen.queryByRole("option", { name: "incluster" })).toBeNull(),
    );
  });
});
