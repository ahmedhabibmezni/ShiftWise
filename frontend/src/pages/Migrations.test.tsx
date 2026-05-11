import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import type { Migration } from "@/api/migrations";
import type { Vm } from "@/api/vms";
import type { User } from "@/api/types";
import { useAuthStore } from "@/store/auth";
import Migrations from "./Migrations";

function makeAuthUser(over: Partial<User> = {}): User {
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
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    roles: [],
    permissions: { migrations: ["*"], vms: ["read"] },
    ...over,
  };
}

function makeVm(over: Partial<Vm> = {}): Vm {
  return {
    id: 10,
    name: "ubuntu-22-prod",
    description: null,
    cpu_cores: 4,
    memory_mb: 8192,
    disk_gb: 80,
    os_type: "linux",
    os_version: "22.04",
    os_name: "Ubuntu 22.04",
    source_hypervisor_id: 1,
    source_uuid: "uuid-1",
    source_name: "ubuntu-22-prod",
    ip_address: "10.0.0.5",
    mac_address: "00:11:22:33:44:55",
    hostname: "ubuntu-22-prod",
    status: "compatible",
    compatibility_status: "compatible",
    compatibility_details: null,
    openshift_vm_name: null,
    openshift_namespace: null,
    openshift_node: null,
    discovered_at: "2026-05-01T10:00:00Z",
    last_seen_at: "2026-05-11T01:00:00Z",
    tags: null,
    custom_metadata: null,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-11T01:00:00Z",
    is_compatible: true,
    is_migrated: false,
    can_migrate: true,
    ...over,
  };
}

function makeMigration(over: Partial<Migration> = {}): Migration {
  return {
    id: 1,
    vm_id: 10,
    status: "pending",
    strategy: "auto",
    target_namespace: "shiftwise-t1",
    target_storage_class: "nfs-client",
    scheduled_at: null,
    started_at: null,
    completed_at: null,
    progress_percentage: 0,
    current_step: null,
    current_step_number: 0,
    total_steps: 7,
    success: null,
    error_message: null,
    error_code: null,
    migration_config: null,
    source_size_gb: 80,
    transferred_gb: 0,
    transfer_rate_mbps: null,
    target_vm_name: null,
    target_node: null,
    requires_conversion: false,
    conversion_format: null,
    conversion_started_at: null,
    conversion_completed_at: null,
    pre_migration_checks: null,
    post_migration_checks: null,
    can_rollback: true,
    tags: null,
    notes: null,
    created_at: "2026-05-11T10:00:00Z",
    updated_at: "2026-05-11T10:00:00Z",
    is_active: true,
    is_completed: false,
    duration_seconds: 0,
    estimated_time_remaining_seconds: 0,
    ...over,
  };
}

function mockStats(over: Record<string, unknown> = {}) {
  return http.get("/api/v1/migrations/stats/summary", () =>
    HttpResponse.json({
      total_migrations: 2,
      completed: 1,
      failed: 0,
      in_progress: 1,
      pending: 0,
      success_rate: 50,
      average_duration_seconds: 600,
      total_data_transferred_gb: 40,
      ...over,
    }),
  );
}

function mockVms(items: Vm[]) {
  return http.get("/api/v1/vms", () =>
    HttpResponse.json({
      total: items.length,
      page: 1,
      page_size: 100,
      items,
    }),
  );
}

function mockList(items: Migration[]) {
  return http.get("/api/v1/migrations", () =>
    HttpResponse.json({
      total: items.length,
      page: 1,
      page_size: 25,
      items,
    }),
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/migrations"]}>
        <Migrations />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Migrations page", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: makeAuthUser(),
      accessToken: "fake",
      bootstrapped: true,
    });
  });

  it("renders the pipeline log and exposes the create CTA when permitted", async () => {
    server.use(
      mockStats(),
      mockVms([makeVm()]),
      mockList([
        makeMigration({ id: 1, status: "transferring", progress_percentage: 42 }),
        makeMigration({ id: 2, status: "completed", progress_percentage: 100, vm_id: 10 }),
      ]),
    );

    renderPage();

    expect(await screen.findByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new migration/i })).toBeInTheDocument();
    // Stats strip wires in
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("hides the create CTA when the operator only has read", async () => {
    useAuthStore.setState({
      user: makeAuthUser({ permissions: { migrations: ["read"] } }),
      accessToken: "fake",
      bootstrapped: true,
    });

    server.use(mockStats(), mockVms([]), mockList([]));

    renderPage();

    expect(await screen.findByText(/ask an operator to create one/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new migration/i })).toBeNull();
  });

  it("filters the list when a status filter is picked", async () => {
    const calls: URL[] = [];
    server.use(
      mockStats(),
      mockVms([makeVm()]),
      http.get("/api/v1/migrations", ({ request }) => {
        calls.push(new URL(request.url));
        return HttpResponse.json({
          total: 0,
          page: 1,
          page_size: 25,
          items: [],
        });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/pipeline log/i);
    await user.selectOptions(screen.getByLabelText(/filter by status/i), "failed");

    await waitFor(() => {
      const last = calls[calls.length - 1];
      expect(last.searchParams.get("status")).toBe("failed");
    });
  });

  it("opens the create drawer and posts vm_id + strategy", async () => {
    let capturedPayload: unknown = null;
    server.use(
      mockStats(),
      mockVms([
        makeVm({ id: 10, name: "ubuntu-22-prod", can_migrate: true }),
        makeVm({ id: 11, name: "windows-2019", can_migrate: false }),
      ]),
      mockList([]),
      http.post("/api/v1/migrations", async ({ request }) => {
        capturedPayload = await request.json();
        return HttpResponse.json(makeMigration({ id: 42 }), { status: 201 });
      }),
      http.post("/api/v1/migrations/42/start", () =>
        HttpResponse.json(
          makeMigration({ id: 42, status: "validating", is_active: true }),
        ),
      ),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /new migration/i }));
    const dialog = await screen.findByRole("dialog", { name: /new migration/i });

    // Only the migratable VM is offered — the windows-2019 row is filtered out.
    const select = within(dialog).getByLabelText(/target vm/i);
    const options = within(select).getAllByRole("option");
    const labels = options.map((o) => o.textContent ?? "");
    expect(labels.some((l) => l.includes("ubuntu-22-prod"))).toBe(true);
    expect(labels.some((l) => l.includes("windows-2019"))).toBe(false);

    await user.selectOptions(select, "10");
    await user.selectOptions(within(dialog).getByLabelText(/strategy/i), "conversion");
    await user.click(within(dialog).getByRole("button", { name: /^create$/i }));

    await waitFor(() => {
      expect(capturedPayload).toMatchObject({
        vm_id: 10,
        strategy: "conversion",
        target_storage_class: "nfs-client",
      });
    });
  });
});
