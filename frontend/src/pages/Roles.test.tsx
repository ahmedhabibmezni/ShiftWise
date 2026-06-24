import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import type { User } from "@/api/types";
import type { RoleDetail } from "@/api/roles";
import { useAuthStore } from "@/store/auth";
import Roles from "./Roles";

function makeAuthUser(over: Partial<User> = {}): User {
  return {
    id: 1,
    email: "admin@shiftwise.local",
    username: "admin",
    first_name: null,
    last_name: null,
    full_name: "admin",
    tenant_id: "t1",
    is_active: true,
    is_verified: true,
    is_superuser: false,
    last_login_at: null,
    last_login_ip: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    roles: [],
    permissions: { roles: ["*"] },
    ...over,
  };
}

function makeRole(over: Partial<RoleDetail> = {}): RoleDetail {
  return {
    id: 1,
    name: "admin",
    description: "Tenant administrator",
    permissions: { vms: ["*"], hypervisors: ["read", "create"] },
    is_active: true,
    is_system_role: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    ...over,
  };
}

function mockResources() {
  return http.get("/api/v1/roles/permissions/resources", () =>
    HttpResponse.json({
      resources: ["vms", "hypervisors", "migrations", "users", "roles", "reports", "settings"],
      actions: ["create", "read", "update", "delete", "*"],
      description: {
        vms: "Virtual machines",
        hypervisors: "Source hypervisors",
        migrations: "Migration operations",
      },
    }),
  );
}

function mockCount(over: Record<string, unknown> = {}) {
  return http.get("/api/v1/roles/count", () =>
    HttpResponse.json({ total: 4, system_roles: 4, custom_roles: 0, ...over }),
  );
}

function mockList(items: RoleDetail[]) {
  return http.get("/api/v1/roles", () => HttpResponse.json(items));
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/roles"]}>
        <Roles />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Roles page", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: makeAuthUser(),
      accessToken: "fake",
      bootstrapped: true,
    });
  });

  it("lists roles and exposes the new-role CTA when permitted", async () => {
    server.use(
      mockCount(),
      mockList([
        makeRole({ id: 1, name: "admin", is_system_role: true }),
        makeRole({
          id: 5,
          name: "project_manager",
          description: "Custom role",
          is_system_role: false,
        }),
      ]),
    );

    renderPage();

    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(screen.getByText("project_manager")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new role/i })).toBeInTheDocument();
  });

  it("hides the new-role CTA for read-only viewers", async () => {
    useAuthStore.setState({
      user: makeAuthUser({ permissions: { roles: ["read"] } }),
      accessToken: "fake",
      bootstrapped: true,
    });

    server.use(mockCount({ total: 0 }), mockList([]));

    renderPage();

    // The table-level empty state copy is unique to the read-only branch.
    expect(await screen.findByText(/no matching roles/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new role/i })).toBeNull();
  });

  it("opens the detail drawer and shows the system-role lock for protected roles", async () => {
    const adminRole = makeRole({
      id: 1,
      name: "admin",
      is_system_role: true,
    });
    server.use(
      mockCount(),
      mockList([adminRole]),
      mockResources(),
      http.get("/api/v1/roles/1", () =>
        HttpResponse.json({ ...adminRole, user_count: 3 }),
      ),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /admin/i }));
    const dialog = await screen.findByRole("dialog", { name: /admin/i });

    expect(
      within(dialog).getByText(/permissions are seeded at install/i),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /^edit$/i })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /^delete$/i })).toBeNull();
  });

  it("creates a custom role with a permissions matrix payload", async () => {
    let captured: unknown = null;
    server.use(
      mockCount(),
      mockList([]),
      mockResources(),
      http.post("/api/v1/roles", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json(
          makeRole({ id: 9, name: "auditor", is_system_role: false }),
          { status: 201 },
        );
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /new role/i }));
    const dialog = await screen.findByRole("dialog", { name: /new role/i });

    await user.type(within(dialog).getByLabelText(/^name$/i), "auditor");
    await user.type(
      within(dialog).getByLabelText(/^description$/i),
      "Read-only auditor",
    );

    // Click "read vms" in the matrix — the cell's aria-label is built as
    // "read vms" in PermissionsMatrix.
    await user.click(await within(dialog).findByLabelText(/^read vms$/i));

    await user.click(within(dialog).getByRole("button", { name: /^create$/i }));

    await waitFor(() => {
      expect(captured).toMatchObject({
        name: "auditor",
        description: "Read-only auditor",
        is_active: true,
        permissions: { vms: ["read"] },
      });
    });
  });
});
