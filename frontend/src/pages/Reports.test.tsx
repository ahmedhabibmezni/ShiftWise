import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
import Reports from "./Reports";

function makeAuthUser(): User {
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
    permissions: { migrations: ["read"], vms: ["read"], reports: ["read"] },
  };
}

function makeMigration(over: Partial<Migration> = {}): Migration {
  return {
    id: 1,
    vm_id: 10,
    status: "completed",
    strategy: "auto",
    target_namespace: "shiftwise-t1",
    target_storage_class: "nfs-client",
    scheduled_at: null,
    started_at: "2026-05-10T08:00:00Z",
    completed_at: "2026-05-10T08:25:00Z",
    progress_percentage: 100,
    current_step: "done",
    current_step_number: 7,
    total_steps: 7,
    success: true,
    error_message: null,
    error_code: null,
    migration_config: null,
    source_size_gb: 80,
    transferred_gb: 80,
    transfer_rate_mbps: 540,
    target_vm_name: "ubuntu-22-prod",
    target_node: "node02",
    requires_conversion: true,
    conversion_format: "vmdk_to_qcow2",
    conversion_started_at: "2026-05-10T08:05:00Z",
    conversion_completed_at: "2026-05-10T08:15:00Z",
    pre_migration_checks: null,
    post_migration_checks: null,
    can_rollback: true,
    tags: null,
    notes: null,
    created_at: "2026-05-10T07:55:00Z",
    updated_at: "2026-05-10T08:25:00Z",
    is_active: false,
    is_completed: true,
    duration_seconds: 1500,
    estimated_time_remaining_seconds: 0,
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
    ip_address: null,
    mac_address: null,
    hostname: null,
    status: "migrated",
    compatibility_status: "compatible",
    compatibility_details: null,
    openshift_vm_name: "ubuntu-22-prod",
    openshift_namespace: "shiftwise-t1",
    openshift_node: "node02",
    discovered_at: "2026-05-01T10:00:00Z",
    last_seen_at: "2026-05-11T01:00:00Z",
    tags: null,
    custom_metadata: null,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-11T01:00:00Z",
    is_compatible: true,
    is_migrated: true,
    can_migrate: false,
    ...over,
  };
}

function mockStats(over: Record<string, unknown> = {}) {
  return http.get("/api/v1/migrations/stats/summary", () =>
    HttpResponse.json({
      total_migrations: 3,
      completed: 2,
      failed: 1,
      in_progress: 0,
      pending: 0,
      success_rate: 66.7,
      average_duration_seconds: 1500,
      total_data_transferred_gb: 160,
      ...over,
    }),
  );
}

function mockMigrations(items: Migration[]) {
  return http.get("/api/v1/migrations", () =>
    HttpResponse.json({
      total: items.length,
      page: 1,
      page_size: 100,
      items,
    }),
  );
}

function mockVms(items: Vm[]) {
  return http.get("/api/v1/vms", () =>
    HttpResponse.json({
      total: items.length,
      page: 1,
      page_size: 200,
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
      <MemoryRouter initialEntries={["/reports"]}>
        <Reports />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Reports page", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: makeAuthUser(),
      accessToken: "fake",
      bootstrapped: true,
    });
  });

  it("renders the stats strip and the history table", async () => {
    server.use(
      mockStats(),
      mockVms([makeVm()]),
      mockMigrations([
        makeMigration({ id: 1, status: "completed" }),
        makeMigration({ id: 2, status: "failed", success: false, transferred_gb: 0 }),
      ]),
    );

    renderPage();

    expect(await screen.findByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    // Success rate is wired in
    expect(screen.getByText("67%")).toBeInTheDocument();
  });

  it("disables the CSV export button when there is no data", async () => {
    server.use(
      mockStats({ total_migrations: 0, completed: 0, failed: 0, success_rate: 0 }),
      mockVms([]),
      mockMigrations([]),
    );

    renderPage();

    // The empty-state announces no history and routes to the first action.
    expect(await screen.findByText(/no history to report/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /go to migrations/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export csv/i })).toBeDisabled();
  });

  it("downloads a CSV blob when the export button is clicked", async () => {
    const created: string[] = [];
    // jsdom doesn't implement createObjectURL — stub it and capture the
    // Blob so we can assert the body.
    const capturedBlobs: Blob[] = [];
    // Bind so the saved references can be restored without the
    // unbound-method lint flagging a `this`-scoping hazard.
    const originalCreate = URL.createObjectURL.bind(URL);
    const originalRevoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = vi.fn((blob: Blob) => {
      capturedBlobs.push(blob);
      const url = `blob:fake-${capturedBlobs.length}`;
      created.push(url);
      return url;
    }) as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;

    // Also stub anchor.click so the test doesn't navigate.
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    try {
      server.use(
        mockStats(),
        mockVms([makeVm()]),
        mockMigrations([makeMigration({ id: 42 })]),
      );

      const user = userEvent.setup();
      renderPage();

      await screen.findByText("#42");

      const button = screen.getByRole("button", { name: /export csv/i });
      await user.click(button);

      await waitFor(() => expect(capturedBlobs.length).toBe(1));
      const text = await capturedBlobs[0].text();
      // BOM-prefixed UTF-8 — strip it then assert content.
      const body = text.replace(/^\uFEFF/, "");
      expect(body.split("\r\n")[0]).toContain("id,vm_id,vm_name");
      expect(body).toContain("42,10,ubuntu-22-prod,completed,auto");
      expect(clickSpy).toHaveBeenCalledTimes(1);
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      clickSpy.mockRestore();
    }
  });

  it("surfaces an error banner when the history fetch fails", async () => {
    server.use(
      mockStats(),
      mockVms([]),
      http.get("/api/v1/migrations", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(/could not load migration history/i),
    ).toBeInTheDocument();
  });
});
