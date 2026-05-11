import { describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import { HypervisorCreateDrawer } from "./HypervisorCreateDrawer";

function renderDrawer() {
  const onClose = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <HypervisorCreateDrawer open onClose={onClose} />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
  return { ...utils, onClose, queryClient };
}

async function fillBaseFields(user: ReturnType<typeof userEvent.setup>) {
  await user.clear(screen.getByLabelText(/^nom$/i));
  await user.type(screen.getByLabelText(/^nom$/i), "lab-kvm");
  await user.clear(screen.getByLabelText(/^host$/i));
  await user.type(
    screen.getByLabelText(/^host$/i),
    "qemu+ssh://user@10.0.0.5/system",
  );
  await user.clear(screen.getByLabelText(/^username$/i));
  await user.type(screen.getByLabelText(/^username$/i), "root");
  await user.type(screen.getByLabelText(/^password$/i), "secret");
}

describe("HypervisorCreateDrawer", () => {
  it("shows a success banner when test-connection succeeds", async () => {
    let testCalls = 0;
    server.use(
      http.post("/api/v1/hypervisors/test-connection", async () => {
        testCalls += 1;
        return HttpResponse.json({
          success: true,
          message: "Connexion réussie · 12 VMs détectées",
          vms_count: 12,
          error: null,
        });
      }),
    );

    const user = userEvent.setup();
    renderDrawer();
    await fillBaseFields(user);
    await user.click(screen.getByRole("button", { name: /tester la connexion/i }));

    await waitFor(() => expect(testCalls).toBe(1));
    const status = await screen.findByRole("status");
    expect(within(status).getByText(/connexion réussie/i)).toBeInTheDocument();
    expect(within(status).getByText(/^12 vms détectées$/i)).toBeInTheDocument();
  });

  it("surfaces the backend error message on test-connection failure", async () => {
    server.use(
      http.post("/api/v1/hypervisors/test-connection", () =>
        HttpResponse.json({
          success: false,
          message: "Échec de la connexion",
          vms_count: null,
          error: "SSH KVM connection failed: timed out",
        }),
      ),
    );

    const user = userEvent.setup();
    renderDrawer();
    await fillBaseFields(user);
    await user.click(screen.getByRole("button", { name: /tester la connexion/i }));

    expect(await screen.findByText(/échec de la connexion/i)).toBeInTheDocument();
    expect(screen.getByText(/ssh kvm connection failed/i)).toBeInTheDocument();
  });

  it("creates the hypervisor and closes the drawer on submit", async () => {
    let createPayload: unknown = null;
    server.use(
      http.post("/api/v1/hypervisors", async ({ request }) => {
        createPayload = await request.json();
        return HttpResponse.json(
          {
            id: 99,
            name: "lab-kvm",
            description: null,
            type: "kvm",
            host: "qemu+ssh://user@10.0.0.5/system",
            port: 22,
            username: "root",
            verify_ssl: false,
            status: "active",
            is_active: true,
            last_sync_at: null,
            last_successful_connection: null,
            last_error: null,
            total_vms_discovered: 0,
            total_vms_migrated: 0,
            connection_config: null,
            tags: null,
            created_at: "2026-05-11T00:00:00Z",
            updated_at: "2026-05-11T00:00:00Z",
            is_reachable: true,
            connection_url: "qemu+ssh://user@10.0.0.5/system",
            needs_sync: true,
          },
          { status: 201 },
        );
      }),
    );

    const user = userEvent.setup();
    const { onClose } = renderDrawer();
    await fillBaseFields(user);
    await user.click(screen.getByRole("button", { name: /^créer$/i }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(createPayload).toMatchObject({
      name: "lab-kvm",
      type: "kvm",
      host: "qemu+ssh://user@10.0.0.5/system",
      port: 22,
      username: "root",
    });
  });

  it("blocks the submit and surfaces validation when required fields are empty", async () => {
    const user = userEvent.setup();
    renderDrawer();

    await user.click(screen.getByRole("button", { name: /^créer$/i }));

    expect(await screen.findByText(/nom requis/i)).toBeInTheDocument();
    expect(screen.getByText(/host requis/i)).toBeInTheDocument();
    expect(screen.getByText(/username requis/i)).toBeInTheDocument();
    expect(screen.getByText(/password requis/i)).toBeInTheDocument();
  });

  it("rewrites the default port when the type changes", async () => {
    const user = userEvent.setup();
    renderDrawer();

    const portInput = screen.getByLabelText(/^port$/i) as HTMLInputElement;
    expect(portInput.value).toBe("22");

    await user.selectOptions(screen.getByLabelText(/^type$/i), "proxmox");
    await waitFor(() => expect(portInput.value).toBe("8006"));

    await user.selectOptions(screen.getByLabelText(/^type$/i), "vmware_workstation");
    await waitFor(() => expect(portInput.value).toBe(""));
  });
});
