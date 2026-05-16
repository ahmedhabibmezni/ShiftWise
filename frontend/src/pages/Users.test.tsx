import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import { useAuthStore } from "@/store/auth";
import type { User } from "@/api/types";
import type { UserListItem } from "@/api/users";
import Users from "./Users";

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
    permissions: { users: ["*"], roles: ["read"] },
    ...over,
  };
}

function makeUserItem(over: Partial<UserListItem> = {}): UserListItem {
  return {
    id: 10,
    email: "alice@shiftwise.local",
    username: "alice",
    first_name: "Alice",
    last_name: "Martin",
    full_name: "Alice Martin",
    tenant_id: "t1",
    is_active: true,
    is_verified: true,
    is_superuser: false,
    last_login_at: null,
    last_login_ip: null,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    ...over,
  };
}

function roleJson(id: number, name: string, description: string) {
  return {
    id,
    name,
    description,
    is_system_role: true,
    permissions: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/users"]}>
        <Users />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Users page", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: makeAuthUser(),
      accessToken: "fake",
      bootstrapped: true,
    });
  });

  it("renders the directory and exposes the new-user CTA when permitted", async () => {
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [
            makeUserItem({ id: 1, username: "alice" }),
            makeUserItem({
              id: 2,
              username: "bob",
              email: "bob@shiftwise.local",
              full_name: "Bob Owner",
              is_superuser: true,
            }),
          ],
          total: 2,
          page: 1,
          page_size: 25,
          pages: 1,
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new user/i })).toBeInTheDocument();
    expect(screen.getByText(/super admin/i)).toBeInTheDocument();
  });

  it("hides the new-user CTA for read-only viewers", async () => {
    useAuthStore.setState({
      user: makeAuthUser({ permissions: { users: ["read"] } }),
      accessToken: "fake",
      bootstrapped: true,
    });

    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          page: 1,
          page_size: 25,
          pages: 0,
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText(/ask a super-admin/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new user/i })).toBeNull();
  });

  it("opens the create drawer and posts the new user payload", async () => {
    let capturedPayload: unknown = null;
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          page: 1,
          page_size: 25,
          pages: 0,
        }),
      ),
      http.get("/api/v1/roles", () =>
        HttpResponse.json([
          {
            id: 3,
            name: "user",
            description: "Standard operator",
            is_system_role: true,
            permissions: {},
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ]),
      ),
      http.post("/api/v1/users", async ({ request }) => {
        capturedPayload = await request.json();
        return HttpResponse.json(
          {
            id: 99,
            email: "newuser@shiftwise.local",
            username: "newuser",
            first_name: "New",
            last_name: "Operator",
            full_name: "New Operator",
            tenant_id: "t1",
            is_active: true,
            is_verified: false,
            is_superuser: false,
            created_at: "2026-05-11T00:00:00Z",
            updated_at: "2026-05-11T00:00:00Z",
            roles: [],
            permissions: {},
          },
          { status: 201 },
        );
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /new user/i }));

    const dialog = await screen.findByRole("dialog", { name: /new user/i });
    await user.type(within(dialog).getByLabelText(/^email$/i), "newuser@shiftwise.local");
    await user.type(within(dialog).getByLabelText(/^username$/i), "newuser");
    await user.type(within(dialog).getByLabelText(/^first name$/i), "New");
    await user.type(within(dialog).getByLabelText(/^last name$/i), "Operator");
    await user.type(within(dialog).getByLabelText(/^password$/i), "Str0ngPass!");

    await waitFor(() =>
      expect(within(dialog).getByRole("option", { name: /standard operator/i })).toBeInTheDocument(),
    );
    await user.selectOptions(within(dialog).getByLabelText(/^role$/i), "3");

    await user.click(within(dialog).getByRole("button", { name: /^create$/i }));

    await waitFor(() => {
      expect(capturedPayload).toMatchObject({
        email: "newuser@shiftwise.local",
        username: "newuser",
        first_name: "New",
        last_name: "Operator",
        tenant_id: "t1",
        password: "Str0ngPass!",
        role_ids: [3],
      });
    });
  });

  it("opens the detail drawer on row click and edits the user with a diff payload", async () => {
    let captured: unknown = null;
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [makeUserItem({ id: 42, username: "alice" })],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        }),
      ),
      http.get("/api/v1/users/42", () =>
        HttpResponse.json({
          id: 42,
          email: "alice@shiftwise.local",
          username: "alice",
          first_name: "Alice",
          last_name: "Martin",
          full_name: "Alice Martin",
          tenant_id: "t1",
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:00Z",
          roles: [],
          permissions: {},
        }),
      ),
      http.get("/api/v1/roles", () => HttpResponse.json([])),
      http.put("/api/v1/users/42", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          id: 42,
          email: "alice@shiftwise.local",
          username: "alice2",
          first_name: "Alice",
          last_name: "Martin",
          full_name: "Alice Martin",
          tenant_id: "t1",
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-05-11T00:00:00Z",
          roles: [],
          permissions: {},
        });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "alice" }));
    const dialog = await screen.findByRole("dialog", { name: /alice/i });
    await user.click(within(dialog).getByRole("button", { name: /^edit$/i }));

    const usernameInput = within(dialog).getByLabelText(/^username$/i);
    await user.clear(usernameInput);
    await user.type(usernameInput, "alice2");

    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      // Diff payload — username changed, everything else is identical.
      expect(captured).toEqual({ username: "alice2" });
    });
  });

  it("pushes the updated user into the auth store when self-editing", async () => {
    // The signed-in user (id=1) opens their own row from the directory
    // and renames themselves. After save, the auth store's user must
    // carry the new username — otherwise the sidebar / RoleStripe stay
    // stale until the next page refresh.
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [makeUserItem({ id: 1, username: "admin" })],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        }),
      ),
      http.get("/api/v1/users/1", () =>
        HttpResponse.json({
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
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          roles: [],
          permissions: { users: ["*"] },
        }),
      ),
      http.get("/api/v1/roles", () => HttpResponse.json([])),
      http.put("/api/v1/users/1", () =>
        HttpResponse.json({
          id: 1,
          email: "admin@shiftwise.local",
          username: "ahmedm",
          first_name: null,
          last_name: null,
          full_name: "Ahmed Mezni",
          tenant_id: "t1",
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-05-11T00:00:00Z",
          roles: [],
          permissions: { users: ["*"] },
        }),
      ),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "admin" }));
    const dialog = await screen.findByRole("dialog", { name: /admin/i });
    await user.click(within(dialog).getByRole("button", { name: /^edit$/i }));

    const usernameInput = within(dialog).getByLabelText(/^username$/i);
    await user.clear(usernameInput);
    await user.type(usernameInput, "ahmedm");

    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(useAuthStore.getState().user?.username).toBe("ahmedm");
      expect(useAuthStore.getState().user?.full_name).toBe("Ahmed Mezni");
    });
  });

  it("hides the delete button on the current user's own account", async () => {
    // The drawer is opened for the signed-in user (id=1). Self-delete is
    // blocked client-side; the backend also enforces this.
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [makeUserItem({ id: 1, username: "admin" })],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        }),
      ),
      http.get("/api/v1/users/1", () =>
        HttpResponse.json({
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
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          roles: [],
          permissions: { users: ["*"] },
        }),
      ),
      http.get("/api/v1/roles", () => HttpResponse.json([])),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "admin" }));
    const dialog = await screen.findByRole("dialog", { name: /admin/i });

    expect(within(dialog).queryByRole("button", { name: /^delete$/i })).toBeNull();
    expect(within(dialog).getByText(/this is your own account/i)).toBeInTheDocument();
  });

  it("deletes another user after confirmation", async () => {
    let deleted = false;
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [makeUserItem({ id: 9, username: "leaver" })],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        }),
      ),
      http.get("/api/v1/users/9", () =>
        HttpResponse.json({
          id: 9,
          email: "leaver@shiftwise.local",
          username: "leaver",
          first_name: null,
          last_name: null,
          full_name: "leaver",
          tenant_id: "t1",
          is_active: true,
          is_verified: false,
          is_superuser: false,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-01T00:00:00Z",
          roles: [],
          permissions: {},
        }),
      ),
      http.get("/api/v1/roles", () => HttpResponse.json([])),
      http.delete("/api/v1/users/9", () => {
        deleted = true;
        return HttpResponse.json({
          message: "Utilisateur leaver@shiftwise.local supprimé avec succès",
          success: true,
        });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "leaver" }));
    const dialog = await screen.findByRole("dialog", { name: /leaver/i });
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    const confirm = await screen.findByRole("alertdialog");
    await user.click(
      within(confirm).getByRole("button", { name: /delete user/i }),
    );

    await waitFor(() => expect(deleted).toBe(true));
  });

  it("surfaces inline validation when required fields are missing", async () => {
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          page: 1,
          page_size: 25,
          pages: 0,
        }),
      ),
      http.get("/api/v1/roles", () => HttpResponse.json([])),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /new user/i }));
    const dialog = await screen.findByRole("dialog", { name: /new user/i });

    // tenant_id is pre-populated from the auth store, clear it to assert the rule.
    await user.clear(within(dialog).getByLabelText(/^tenant$/i));
    await user.click(within(dialog).getByRole("button", { name: /^create$/i }));

    expect(await within(dialog).findByText(/email is required/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/must be at least 3 characters/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/tenant is required/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/must be at least 8 characters/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/role is required/i)).toBeInTheDocument();
  });

  it("omits the super_admin role from the create drawer for a non-superuser", async () => {
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 25, pages: 0 }),
      ),
      http.get("/api/v1/roles", () =>
        HttpResponse.json([
          roleJson(1, "super_admin", "Full platform access"),
          roleJson(2, "admin", "Tenant administrator"),
          roleJson(3, "user", "Standard operator"),
        ]),
      ),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /new user/i }));
    const dialog = await screen.findByRole("dialog", { name: /new user/i });

    await waitFor(() =>
      expect(
        within(dialog).getByRole("option", { name: /tenant administrator/i }),
      ).toBeInTheDocument(),
    );
    const roleLabels = within(within(dialog).getByLabelText(/^role$/i))
      .getAllByRole("option")
      .map((o) => o.textContent ?? "");
    expect(roleLabels.some((l) => l.includes("super_admin"))).toBe(false);
  });

  it("hides edit and delete when a non-superuser opens a super-admin account", async () => {
    server.use(
      http.get("/api/v1/users", () =>
        HttpResponse.json({
          items: [makeUserItem({ id: 7, username: "root", is_superuser: true })],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        }),
      ),
      http.get("/api/v1/users/7", () =>
        HttpResponse.json({
          id: 7,
          email: "root@shiftwise.local",
          username: "root",
          first_name: null,
          last_name: null,
          full_name: "root",
          tenant_id: "t1",
          is_active: true,
          is_verified: true,
          is_superuser: true,
          last_login_at: null,
          last_login_ip: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          roles: [],
          permissions: {},
        }),
      ),
      http.get("/api/v1/roles", () => HttpResponse.json([])),
    );

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "root" }));
    const dialog = await screen.findByRole("dialog", { name: /root/i });

    await waitFor(() =>
      expect(
        within(dialog).getByText(/can only be modified by another/i),
      ).toBeInTheDocument(),
    );
    expect(within(dialog).queryByRole("button", { name: /^edit$/i })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /^delete$/i })).toBeNull();
  });
});
