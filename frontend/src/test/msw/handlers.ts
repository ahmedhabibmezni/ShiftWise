import { http, HttpResponse } from "msw";
import type { User } from "@/api/types";

export const mockUser: User = {
  id: 1,
  email: "test@shiftwise.local",
  username: "testuser",
  first_name: "Test",
  last_name: "User",
  full_name: "Test User",
  tenant_id: "tenant-a",
  is_active: true,
  is_verified: true,
  is_superuser: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  roles: [
    {
      id: 2,
      name: "admin",
      description: "Admin role",
      is_system_role: true,
      permissions: {},
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
  permissions: { vms: ["read"] },
};

export const handlers = {
  loginSuccess: http.post("/api/v1/auth/login", () =>
    HttpResponse.json({
      access_token: "fake-access-token",
      token_type: "bearer",
      expires_in: 900,
    }),
  ),
  loginInvalidCredentials: http.post("/api/v1/auth/login", () =>
    HttpResponse.json(
      { detail: "Invalid email or password" },
      { status: 401 },
    ),
  ),
  loginInactive: http.post("/api/v1/auth/login", () =>
    HttpResponse.json(
      { detail: "Account inactive. Contact the administrator." },
      { status: 403 },
    ),
  ),
  loginNetworkError: http.post("/api/v1/auth/login", () => HttpResponse.error()),
  meSuccess: http.get("/api/v1/auth/me", () => HttpResponse.json(mockUser)),
};
