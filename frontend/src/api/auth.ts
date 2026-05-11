import { api } from "@/lib/axios";
import type { LoginRequest, TokenResponse, User } from "@/api/types";

export async function login(payload: LoginRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>("/auth/login", payload);
  return res.data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}

export async function fetchCurrentUser(): Promise<User> {
  const res = await api.get<User>("/auth/me");
  return res.data;
}
