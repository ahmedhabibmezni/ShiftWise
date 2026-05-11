import { create } from "zustand";
import type { User } from "@/api/types";

type AuthState = {
  user: User | null;
  accessToken: string | null;
  bootstrapped: boolean;
};

type AuthActions = {
  setAccessToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  setSession: (token: string, user: User) => void;
  clearSession: () => void;
  markBootstrapped: () => void;
};

export const useAuthStore = create<AuthState & AuthActions>((set) => ({
  user: null,
  accessToken: null,
  bootstrapped: false,
  setAccessToken: (token) => set({ accessToken: token }),
  setUser: (user) => set({ user }),
  setSession: (token, user) => set({ accessToken: token, user }),
  clearSession: () => set({ accessToken: null, user: null }),
  markBootstrapped: () => set({ bootstrapped: true }),
}));

export function getAccessToken(): string | null {
  return useAuthStore.getState().accessToken;
}

export function setAccessToken(token: string | null): void {
  useAuthStore.getState().setAccessToken(token);
}

export function clearSession(): void {
  useAuthStore.getState().clearSession();
}
