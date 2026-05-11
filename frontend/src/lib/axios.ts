import axios from "axios";
import type { AxiosError, AxiosRequestConfig, AxiosResponse } from "axios";
import { clearSession, getAccessToken, setAccessToken } from "@/store/auth";
import type { TokenResponse } from "@/api/types";

const API_BASE = "/api/v1";
const REFRESH_PATH = "/auth/refresh";
const LOGIN_PATH = "/auth/login";

// Endpoints that must never trigger the 401 -> refresh -> replay flow.
// Hitting refresh from refresh would loop; the login endpoint is the entry
// point and a 401 there means "bad credentials", not "stale access token".
const REFRESH_EXEMPT_PATHS = new Set<string>([REFRESH_PATH, LOGIN_PATH]);

type RetryableRequest = AxiosRequestConfig & { _retry?: boolean };

export const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }
  return config;
});

// Single-flight refresh: even when several pending requests get 401 at the
// same time, only one /auth/refresh is dispatched. The others await the
// same promise then replay with the rotated access token.
let refreshPromise: Promise<string> | null = null;

async function runRefresh(): Promise<string> {
  const res: AxiosResponse<TokenResponse> = await axios.post(
    `${API_BASE}${REFRESH_PATH}`,
    {},
    { withCredentials: true },
  );
  const newToken = res.data.access_token;
  setAccessToken(newToken);
  return newToken;
}

function isRefreshExempt(url: string | undefined): boolean {
  if (!url) return false;
  return Array.from(REFRESH_EXEMPT_PATHS).some((path) => url.includes(path));
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetryableRequest | undefined;
    const status = error.response?.status;

    if (status !== 401 || !original || original._retry || isRefreshExempt(original.url)) {
      return Promise.reject(error);
    }

    original._retry = true;

    try {
      if (refreshPromise === null) {
        refreshPromise = runRefresh().finally(() => {
          refreshPromise = null;
        });
      }
      const newToken = await refreshPromise;
      original.headers = original.headers ?? {};
      (original.headers as Record<string, string>)["Authorization"] = `Bearer ${newToken}`;
      return api.request(original);
    } catch (refreshErr) {
      clearSession();
      return Promise.reject(refreshErr);
    }
  },
);

export async function bootstrapAuth(): Promise<boolean> {
  // Called once at app startup. Tries to silently rehydrate the session
  // from the refresh cookie. Returns true if we end up authenticated.
  try {
    await runRefresh();
    return true;
  } catch {
    clearSession();
    return false;
  }
}
