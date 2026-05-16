import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import type { Vm } from "@/api/vms";
import type { User } from "@/api/types";
import { useAuthStore } from "@/store/auth";
import Vms from "./Vms";

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
    permissions: { vms: ["*"], hypervisors: ["read"] },
    ...over,
  };
}

function makeVm(over: Partial<Vm> = {}): Vm {
  return {
    id: 1,
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
    status: "discovered",
    compatibility_status: "unknown",
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
    is_compatible: false,
    is_migrated: false,
    can_migrate: false,
    ...over,
  };
}

function mockHypervisorsAll() {
  return http.get("/api/v1/hypervisors", () =>
    HttpResponse.json({
      total: 1,
      page: 1,
      page_size: 100,
      items: [
        {
          id: 1,
          name: "lab-kvm",
          description: null,
          type: "kvm",
          host: "qemu+ssh://...",
          port: 22,
          username: "root",
          verify_ssl: false,
          status: "active",
          is_active: true,
          last_sync_at: null,
          last_successful_connection: null,
          last_error: null,
          total_vms_discovered: 1,
          total_vms_migrated: 0,
          connection_config: null,
          tags: null,
          created_at: "2026-05-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:00Z",
          is_reachable: true,
          connection_url: "kvm://lab",
          needs_sync: false,
        },
      ],
    }),
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/vms"]}>
        <Vms />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Vms page", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: makeAuthUser(),
      accessToken: "fake",
      bootstrapped: true,
    });
  });

  it("renders rows with status + compatibility badges", async () => {
    server.use(
      mockHypervisorsAll(),
      http.get("/api/v1/vms", () =>
        HttpResponse.json({
          total: 2,
          page: 1,
          page_size: 25,
          items: [
            makeVm({ id: 1, name: "ubuntu-22-prod", status: "discovered", compatibility_status: "unknown" }),
            makeVm({
              id: 2,
              name: "centos-legacy",
              status: "discovered",
              compatibility_status: "incompatible",
            }),
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("ubuntu-22-prod")).toBeInTheDocument();
    expect(screen.getByText("centos-legacy")).toBeInTheDocument();
    expect(screen.getByText(/1–2 of 2/)).toBeInTheDocument();
  });

  it("forwards compatibility filter to the API", async () => {
    const captured: string[] = [];
    server.use(
      mockHypervisorsAll(),
      http.get("/api/v1/vms", ({ request }) => {
        captured.push(new URL(request.url).search);
        return HttpResponse.json({ total: 0, page: 1, page_size: 25, items: [] });
      }),
    );

    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(captured.length).toBeGreaterThan(0));

    await user.selectOptions(
      screen.getByLabelText(/filter by compatibility/i),
      "incompatible",
    );

    await waitFor(() => {
      expect(captured.some((s) => s.includes("compatibility=incompatible"))).toBe(true);
    });
  });

  it("opens the drawer, runs analyze, renders blockers + grade", async () => {
    const vm = makeVm({ id: 7, name: "ubuntu-22-prod" });
    const analyzed: Vm = {
      ...vm,
      compatibility_status: "incompatible",
      compatibility_details: {
        score: 35,
        grade: "INCOMPATIBLE",
        engine: "rules",
        confidence: null,
        model_grade: null,
        override_reason: null,
        rules: [],
        blockers: [
          { rule: "OS_NOT_SUPPORTED", severity: "blocker", message: "OS family not supported" },
        ],
        warnings: [
          { rule: "MEM_LOW", severity: "warning", message: "Memory below recommended 1GB" },
        ],
        analyzed_at: "2026-05-11T01:00:00Z",
      },
    };

    server.use(
      mockHypervisorsAll(),
      http.get("/api/v1/vms", () =>
        HttpResponse.json({ total: 1, page: 1, page_size: 25, items: [vm] }),
      ),
      http.get("/api/v1/vms/7", () => HttpResponse.json(vm)),
      http.post("/api/v1/vms/7/analyze", () => HttpResponse.json(analyzed)),
    );

    const user = userEvent.setup();
    renderPage();

    const trigger = await screen.findByRole("button", { name: "ubuntu-22-prod" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: /ubuntu-22-prod/i });
    expect(within(dialog).getByText(/not analyzed/i)).toBeInTheDocument();

    server.use(http.get("/api/v1/vms/7", () => HttpResponse.json(analyzed)));

    await user.click(within(dialog).getByRole("button", { name: /^analyze$/i }));

    await waitFor(() => {
      expect(within(dialog).getByText("INCOMPATIBLE")).toBeInTheDocument();
    });
    expect(within(dialog).getByText(/os family not supported/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/memory below recommended/i)).toBeInTheDocument();
  });

  it("surfaces an error banner when the list fails", async () => {
    server.use(
      mockHypervisorsAll(),
      http.get("/api/v1/vms", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(/could not load vms/i),
    ).toBeInTheDocument();
  });

  it("hides the analyze button for read-only viewers", async () => {
    useAuthStore.setState({
      user: makeAuthUser({ permissions: { vms: ["read"], hypervisors: ["read"] } }),
      accessToken: "fake",
      bootstrapped: true,
    });

    const vm = makeVm({ id: 4, name: "viewer-vm" });
    server.use(
      mockHypervisorsAll(),
      http.get("/api/v1/vms", () =>
        HttpResponse.json({ total: 1, page: 1, page_size: 25, items: [vm] }),
      ),
      http.get("/api/v1/vms/4", () => HttpResponse.json(vm)),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "viewer-vm" }));
    const dialog = await screen.findByRole("dialog", { name: /viewer-vm/i });
    expect(within(dialog).queryByRole("button", { name: /^analyze$/i })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /^re-analyze$/i })).toBeNull();
  });
});
