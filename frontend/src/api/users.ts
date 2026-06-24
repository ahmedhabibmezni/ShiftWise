import { api } from "@/lib/axios";
import type { Paginated, Role, User } from "@/api/types";

export type UserListItem = {
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
};

/** Unified pagination envelope — `/users` also sends a `pages` count. */
export type UserListResponse = Paginated<UserListItem>;

export type ListUsersParams = {
  skip?: number;
  limit?: number;
  search?: string;
  is_active?: boolean;
  is_superuser?: boolean;
  tenant_id?: string;
};

export async function listUsers(params: ListUsersParams = {}): Promise<UserListResponse> {
  const res = await api.get<UserListResponse>("/users", { params });
  return res.data;
}

export async function getUser(id: number): Promise<User> {
  const res = await api.get<User>(`/users/${id}`);
  return res.data;
}

export type CreateUserPayload = {
  email: string;
  username: string;
  first_name?: string | null;
  last_name?: string | null;
  tenant_id: string;
  is_active?: boolean;
  password: string;
  role_ids: number[];
};

export async function createUser(payload: CreateUserPayload): Promise<User> {
  const res = await api.post<User>("/users", payload);
  return res.data;
}

export type UpdateUserPayload = {
  email?: string;
  username?: string;
  first_name?: string | null;
  last_name?: string | null;
  password?: string;
  is_active?: boolean;
  role_ids?: number[];
};

export async function updateUser(
  id: number,
  payload: UpdateUserPayload,
): Promise<User> {
  const res = await api.put<User>(`/users/${id}`, payload);
  return res.data;
}

export async function deleteUser(id: number): Promise<{ message: string; success: boolean }> {
  const res = await api.delete<{ message: string; success: boolean }>(`/users/${id}`);
  return res.data;
}

export async function listRoles(): Promise<Role[]> {
  const res = await api.get<Role[]>("/roles");
  return res.data;
}
