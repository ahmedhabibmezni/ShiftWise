import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Toaster } from "react-hot-toast";
import { server } from "@/test/msw/server";
import type { User } from "@/api/types";
import { useAuthStore } from "@/store/auth";
import Settings from "./Settings";

function makeUser(over: Partial<User> = {}): User {
  return {
    id: 7,
    email: "ahmed@nextstep.tn",
    username: "ahmedm",
    first_name: "Ahmed",
    last_name: "Mezni",
    full_name: "Ahmed Mezni",
    tenant_id: "nextstep",
    is_active: true,
    is_verified: true,
    is_superuser: false,
    last_login_at: null,
    last_login_ip: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    roles: [],
    permissions: {},
    ...over,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/settings"]}>
        <Settings />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

describe("Settings page", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: makeUser(),
      accessToken: "fake",
      bootstrapped: true,
    });
  });

  it("renders the identity card with role and tenant", () => {
    renderPage();
    expect(screen.getByText("Ahmed Mezni")).toBeInTheDocument();
    expect(screen.getByText(/tenant · nextstep/i)).toBeInTheDocument();
  });

  it("ships only the changed fields when the profile form is saved", async () => {
    let captured: unknown = null;
    server.use(
      http.put("/api/v1/users/7", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          ...makeUser(),
          email: "ahmed.mezni@nextstep.tn",
          updated_at: "2026-05-11T00:00:00Z",
        });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    const email = screen.getByLabelText(/^email$/i);
    await user.clear(email);
    await user.type(email, "ahmed.mezni@nextstep.tn");

    await user.click(screen.getByRole("button", { name: /save profile/i }));

    await waitFor(() => {
      // Diff payload — only the email moved.
      expect(captured).toEqual({ email: "ahmed.mezni@nextstep.tn" });
    });
  });

  it("validates password complexity inline before contacting the API", async () => {
    let called = false;
    server.use(
      http.put("/api/v1/users/7", () => {
        called = true;
        return HttpResponse.json(makeUser());
      }),
    );

    const user = userEvent.setup();
    renderPage();

    const password = screen.getByLabelText(/new password/i);
    await user.type(screen.getByLabelText(/current password/i), "old-Pass1!");
    await user.type(password, "short");
    await user.type(screen.getByLabelText(/^confirm$/i), "short");

    await user.click(screen.getByRole("button", { name: /change password/i }));

    expect(await screen.findByText(/must be at least 8 characters/i)).toBeInTheDocument();
    expect(called).toBe(false);
  });

  it("posts the new password when the form is valid", async () => {
    let captured: unknown = null;
    server.use(
      http.put("/api/v1/users/7", async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json(makeUser());
      }),
    );

    const user = userEvent.setup();
    renderPage();

    // Scope to the password section to avoid accidentally hitting the
    // profile form's submit button. The section's submit label is unique.
    const passwordForm = screen.getByRole("button", { name: /change password/i }).closest("form")!;
    await user.type(within(passwordForm).getByLabelText(/current password/i), "old-Pass1!");
    await user.type(within(passwordForm).getByLabelText(/new password/i), "NewSecret9!");
    await user.type(within(passwordForm).getByLabelText(/^confirm$/i), "NewSecret9!");

    await user.click(within(passwordForm).getByRole("button", { name: /change password/i }));

    await waitFor(() => {
      // Only the new password ships — current_password is a client-side guard.
      expect(captured).toEqual({ password: "NewSecret9!" });
    });
  });

  it("flags a confirmation mismatch", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/current password/i), "old-Pass1!");
    await user.type(screen.getByLabelText(/new password/i), "NewSecret9!");
    await user.type(screen.getByLabelText(/^confirm$/i), "Different9!");

    await user.click(screen.getByRole("button", { name: /change password/i }));

    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
  });
});
