import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "@/test/msw/server";
import { handlers, mockUser } from "@/test/msw/handlers";
import { useAuthStore } from "@/store/auth";
import Login from "./Login";

function renderLogin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Login page", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, bootstrapped: true });
  });

  it("authenticates the user and lands on the home route", async () => {
    server.use(handlers.loginSuccess, handlers.meSuccess);
    const user = userEvent.setup();

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "test@shiftwise.local");
    await user.type(screen.getByLabelText(/password/i), "Password123!");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => {
      expect(screen.getByText("HOME")).toBeInTheDocument();
    });

    const state = useAuthStore.getState();
    expect(state.accessToken).toBe("fake-access-token");
    expect(state.user?.username).toBe(mockUser.username);
  });

  it("shows an inline error on 401 invalid credentials", async () => {
    server.use(handlers.loginInvalidCredentials);
    const user = userEvent.setup();

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "test@shiftwise.local");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    const alert = await screen.findByText(/login failed/i);
    expect(alert).toBeInTheDocument();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("surfaces the inactive-account message on 403", async () => {
    server.use(handlers.loginInactive);
    const user = userEvent.setup();

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "test@shiftwise.local");
    await user.type(screen.getByLabelText(/password/i), "Password123!");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText(/account inactive/i)).toBeInTheDocument();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("flags client-side validation when fields are empty", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText(/email required/i)).toBeInTheDocument();
    expect(screen.getByText(/password required/i)).toBeInTheDocument();
  });
});
