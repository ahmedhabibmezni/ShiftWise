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

/**
 * Unified pagination envelope for every list endpoint.
 *
 * The backend list routes (`/users`, `/vms`, `/hypervisors`, `/migrations`)
 * all return `{ items, total, page, page_size }`. Only `/users` additionally
 * sends a precomputed `pages` count — so it is optional here. Consumers that
 * need a page count should call `totalPages()` rather than reading `pages`,
 * which derives it consistently whether the field is present or not.
 *
 * Before this type the four responses were declared independently with
 * subtly different field orders and an inconsistent `pages` field.
 */
export type Paginated<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  /** Precomputed page count — only some endpoints send it. Prefer `totalPages()`. */
  pages?: number;
};

/**
 * Derive the page count from a paginated envelope. Uses the backend-supplied
 * `pages` when present; otherwise computes it from `total` / `page_size`.
 * Always returns at least 1 so pagination controls render sanely on an
 * empty list.
 */
export function totalPages(p: {
  total: number;
  page_size: number;
  pages?: number;
}): number {
  if (typeof p.pages === "number" && p.pages > 0) return p.pages;
  if (p.page_size <= 0) return 1;
  return Math.max(1, Math.ceil(p.total / p.page_size));
}
