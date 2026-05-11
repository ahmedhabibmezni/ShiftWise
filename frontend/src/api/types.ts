export type Role = {
  id: number;
  name: string;
  description: string | null;
  is_system_role: boolean;
  permissions: Record<string, string[]>;
  created_at: string;
  updated_at: string;
};

export type User = {
  id: number;
  email: string;
  username: string;
  first_name: string | null;
  last_name: string | null;
  full_name: string;
  tenant_id: string;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  last_login_at: string | null;
  last_login_ip: string | null;
  created_at: string;
  updated_at: string;
  roles: Role[];
  permissions: Record<string, string[]>;
};

export type LoginRequest = {
  email: string;
  password: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
};

export type ApiError = {
  detail: string;
};
