import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { useAuthStore } from "@/store/auth";
import type { Role, User } from "@/api/types";
import { RoleStripe } from "./RoleStripe";

function makeRole(name: string): Role {
  return {
    id: 1,
    name,
    description: null,
    is_system_role: true,
    permissions: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function makeUser(over: Partial<User> = {}): User {
  return {
    id: 1,
    email: "ahmed@nextstep.tn",
    username: "ahmed",
    first_name: "Ahmed",
    last_name: "Mezni",
    full_name: "Ahmed Mezni",
    tenant_id: "nextstep",
    is_active: true,
    is_verified: true,
    is_superuser: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    roles: [],
    permissions: {},
    ...over,
  };
}

describe("RoleStripe", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, bootstrapped: true });
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, bootstrapped: true });
  });

  it("renders nothing when the operator is not signed in", () => {
    const { container } = render(<RoleStripe />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows ADMINISTRATOR for an admin role + the tenant + the capabilities line", () => {
    useAuthStore.setState({
      user: makeUser({ roles: [makeRole("admin")] }),
      accessToken: "fake",
      bootstrapped: true,
    });

    render(<RoleStripe />);
    expect(screen.getByText("ADMINISTRATOR")).toBeInTheDocument();
    expect(screen.getByText("Ahmed Mezni")).toBeInTheDocument();
    expect(screen.getByText(/tenant · nextstep/i)).toBeInTheDocument();
    expect(screen.getByText(/full control on this tenant/i)).toBeInTheDocument();
    const region = screen.getByRole("region", { name: /current operator role/i });
    expect(region).toHaveAttribute("data-role", "admin");
  });

  it("forces SUPER ADMIN for super-users even when other roles are present", () => {
    useAuthStore.setState({
      user: makeUser({
        is_superuser: true,
        roles: [makeRole("viewer")],
      }),
      accessToken: "fake",
      bootstrapped: true,
    });

    render(<RoleStripe />);
    expect(screen.getByText("SUPER ADMIN")).toBeInTheDocument();
    expect(screen.queryByText("VIEWER")).toBeNull();
    expect(screen.getByRole("region")).toHaveAttribute("data-role", "super_admin");
  });

  it("shows VIEWER with the read-only capability copy", () => {
    useAuthStore.setState({
      user: makeUser({ roles: [makeRole("viewer")] }),
      accessToken: "fake",
      bootstrapped: true,
    });

    render(<RoleStripe />);
    expect(screen.getByText("VIEWER")).toBeInTheDocument();
    expect(screen.getByText(/browse only/i)).toBeInTheDocument();
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
  });

  it("falls back to the user's username when full_name is empty", () => {
    useAuthStore.setState({
      user: makeUser({
        full_name: "",
        username: "guest42",
        roles: [makeRole("user")],
      }),
      accessToken: "fake",
      bootstrapped: true,
    });

    render(<RoleStripe />);
    expect(screen.getByText("guest42")).toBeInTheDocument();
  });
});
