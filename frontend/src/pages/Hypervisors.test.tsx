import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import type { Hypervisor } from "@/api/hypervisors";
import type { User } from "@/api/types";
import { useAuthStore } from "@/store/auth";
import Hypervisors from "./Hypervisors";

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
    permissions: { hypervisors: ["*"], vms: ["*"] },
    ...over,
  };
}

function makeHypervisor(over: Partial<Hypervisor> = {}): Hypervisor {
  return {
    id: 1,
    name: "vsphere-prod",
    description: null,
    type: "vsphere",
    host: "10.0.0.10",
    port: 443,
    username: "administrator@vsphere.local",
    verify_ssl: false,
    status: "active",
    is_active: true,
    last_sync_at: "2026-05-11T01:00:00Z",
    last_successful_connection: "2026-05-11T01:00:00Z",
    last_error: null,
    total_vms_discovered: 42,
    total_vms_migrated: 5,
    connection_config: null,
    tags: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-05-11T01:00:00Z",
    is_reachable: true,
    connection_url: "https://10.0.0.10:443",
    needs_sync: false,
    ...over,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/hypervisors"]}>
        <Hypervisors />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Hypervisors page", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: makeUser(),
      accessToken: "fake",
      bootstrapped: true,
    });
  });

  it("renders the list returned by the API", async () => {
    server.use(
      http.get("/api/v1/hypervisors", () =>
        HttpResponse.json({
          total: 2,
          page: 1,
          page_size: 25,
          items: [
            makeHypervisor({ id: 1, name: "vsphere-prod", type: "vsphere", host: "10.0.0.10" }),
            makeHypervisor({
              id: 2,
              name: "kvm-lab",
              type: "kvm",
              host: "10.0.0.20",
              status: "error",
              total_vms_discovered: 3,
            }),
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("vsphere-prod")).toBeInTheDocument();
    expect(screen.getByText("kvm-lab")).toBeInTheDocument();
    expect(screen.getAllByText(/active/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/1–2 of 2/)).toBeInTheDocument();
  });

  it("forwards filters to the API and re-queries", async () => {
    const recorded: string[] = [];
    server.use(
      http.get("/api/v1/hypervisors", ({ request }) => {
        const url = new URL(request.url);
        recorded.push(url.search);
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

    await waitFor(() => expect(recorded.length).toBeGreaterThan(0));

    const typeSelect = screen.getByLabelText(/filter by type/i);
    await user.selectOptions(typeSelect, "kvm");

    await waitFor(() => {
      expect(recorded.some((s) => s.includes("type=kvm"))).toBe(true);
    });
  });

  it("opens the detail drawer and triggers sync", async () => {
    const target = makeHypervisor({ id: 7, name: "kvm-east" });
    server.use(
      http.get("/api/v1/hypervisors", () =>
        HttpResponse.json({
          total: 1,
          page: 1,
          page_size: 25,
          items: [target],
        }),
      ),
      http.get("/api/v1/hypervisors/7", () => HttpResponse.json(target)),
      http.get("/api/v1/hypervisors/7/vms", () =>
        HttpResponse.json({
          hypervisor_id: 7,
          hypervisor_name: "kvm-east",
          total_vms: 0,
          vms: [],
        }),
      ),
      http.post("/api/v1/hypervisors/7/sync", () =>
        HttpResponse.json({
          hypervisor_id: 7,
          hypervisor_name: "kvm-east",
          status: "success",
          message: "ok",
          total_discovered: 12,
          new_vms: 4,
          updated_vms: 8,
          archived_vms: 0,
          errors: 0,
        }),
      ),
    );

    const user = userEvent.setup();
    renderPage();

    const trigger = await screen.findByRole("button", { name: "kvm-east" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: /kvm-east/i });
    expect(within(dialog).getByText("administrator@vsphere.local")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /sync now/i }));

    await waitFor(() => {
      expect(screen.getByText(/sync ok/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/12 discovered/)).toBeInTheDocument();
    expect(screen.getByText(/4 new/)).toBeInTheDocument();
  });

  it("tests connectivity of an existing hypervisor from the drawer", async () => {
    const target = makeHypervisor({ id: 8, name: "pve-lab" });
    server.use(
      http.get("/api/v1/hypervisors", () =>
        HttpResponse.json({ total: 1, page: 1, page_size: 25, items: [target] }),
      ),
      http.get("/api/v1/hypervisors/8", () => HttpResponse.json(target)),
      http.get("/api/v1/hypervisors/8/vms", () =>
        HttpResponse.json({
          hypervisor_id: 8,
          hypervisor_name: "pve-lab",
          total_vms: 0,
          vms: [],
        }),
      ),
      http.post("/api/v1/hypervisors/8/test-connection", () =>
        HttpResponse.json({
          success: true,
          message: "Connexion réussie · 9 VMs détectées",
          vms_count: 9,
          error: null,
        }),
      ),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "pve-lab" }));
    const dialog = await screen.findByRole("dialog", { name: /pve-lab/i });

    await user.click(
      within(dialog).getByRole("button", { name: /test connection/i }),
    );

    await waitFor(() => {
      expect(screen.getByText(/9 VMs détectées/)).toBeInTheDocument();
    });
  });

  it("submits a partial update from the edit mode (only changed fields)", async () => {
    let captured: unknown = null;
    const target = makeHypervisor({ id: 5, name: "kvm-old", host: "10.0.0.55" });
    server.use(
      http.get("/api/v1/hypervisors", () =>
        HttpResponse.json({ total: 1, page: 1, page_size: 25, items: [target] }),
      ),
      http.get("/api/v1/hypervisors/5", () => HttpResponse.json(target)),
      http.get("/api/v1/hypervisors/5/vms", () =>
        HttpResponse.json({
          hypervisor_id: 5,
          hypervisor_name: "kvm-old",
          total_vms: 0,
          vms: [],
        }),
      ),
      http.put("/api/v1/hypervisors/5", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({ ...target, name: "kvm-renamed" });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "kvm-old" }));
    const dialog = await screen.findByRole("dialog", { name: /kvm-old/i });
    await user.click(within(dialog).getByRole("button", { name: /^edit$/i }));

    const nameInput = within(dialog).getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "kvm-renamed");

    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      // Only `name` should be in the payload — host/port/etc were unchanged.
      expect(captured).toEqual({ name: "kvm-renamed" });
    });
  });

  it("deletes a hypervisor after confirmation", async () => {
    let deleted = false;
    const target = makeHypervisor({ id: 11, name: "stale-host" });
    server.use(
      http.get("/api/v1/hypervisors", () =>
        HttpResponse.json({ total: 1, page: 1, page_size: 25, items: [target] }),
      ),
      http.get("/api/v1/hypervisors/11", () => HttpResponse.json(target)),
      http.get("/api/v1/hypervisors/11/vms", () =>
        HttpResponse.json({
          hypervisor_id: 11,
          hypervisor_name: "stale-host",
          total_vms: 0,
          vms: [],
        }),
      ),
      http.delete("/api/v1/hypervisors/11", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "stale-host" }));
    const dialog = await screen.findByRole("dialog", { name: /stale-host/i });
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    const confirm = await screen.findByRole("alertdialog");
    await user.click(
      within(confirm).getByRole("button", { name: /delete hypervisor/i }),
    );

    await waitFor(() => expect(deleted).toBe(true));
  });

  it("surfaces an error banner when the list fails", async () => {
    server.use(
      http.get("/api/v1/hypervisors", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(/could not load hypervisors/i),
    ).toBeInTheDocument();
  });

  it("hides create and sync controls for read-only viewers", async () => {
    useAuthStore.setState({
      user: makeUser({ permissions: { hypervisors: ["read"] } }),
      accessToken: "fake",
      bootstrapped: true,
    });

    const target = makeHypervisor({ id: 9, name: "view-only-host" });
    server.use(
      http.get("/api/v1/hypervisors", () =>
        HttpResponse.json({
          total: 1,
          page: 1,
          page_size: 25,
          items: [target],
        }),
      ),
      http.get("/api/v1/hypervisors/9", () => HttpResponse.json(target)),
      http.get("/api/v1/hypervisors/9/vms", () =>
        HttpResponse.json({
          hypervisor_id: 9,
          hypervisor_name: "view-only-host",
          total_vms: 0,
          vms: [],
        }),
      ),
    );

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("view-only-host");
    expect(screen.queryByRole("button", { name: /new hypervisor/i })).toBeNull();

    await user.click(screen.getByRole("button", { name: "view-only-host" }));
    const dialog = await screen.findByRole("dialog", { name: /view-only-host/i });
    expect(within(dialog).queryByRole("button", { name: /sync now/i })).toBeNull();
    expect(
      within(dialog).queryByRole("button", { name: /test connection/i }),
    ).toBeNull();
  });
});
