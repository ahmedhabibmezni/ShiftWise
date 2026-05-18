import axios from "axios";
import type { AxiosError, AxiosRequestConfig, AxiosResponse } from "axios";
import toast from "react-hot-toast";
import { clearSession, getAccessToken, setAccessToken } from "@/store/auth";
import { forceLogout } from "@/lib/session";
import type { TokenResponse } from "@/api/types";

const API_BASE = "/api/v1";
const REFRESH_PATH = "/auth/refresh";
const LOGIN_PATH = "/auth/login";

// Endpoints that must never trigger the 401 -> refresh -> replay flow.
// Hitting refresh from refresh would loop; the login endpoint is the entry
// point and a 401 there means "bad credentials", not "stale access token".
const REFRESH_EXEMPT_PATHS = new Set<string>([REFRESH_PATH, LOGIN_PATH]);

// Shown when an operator deactivates an account whose owner is currently
// signed in. The backend tags the 403 with an X-Account-Status header.
const ACCOUNT_DEACTIVATED_MESSAGE =
  "Your account has been deactivated by an administrator. Contact your administrator to regain access.";

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
  // Exact path match, not substring. A substring test (`url.includes`)
  // would also exempt sibling endpoints — e.g. `/auth/login-attempts`
  // contains `/auth/login` — silently disabling the 401-refresh flow for
  // a genuinely protected route. Strip any query string, then compare.
  const path = url.split("?")[0].split("#")[0];
  return REFRESH_EXEMPT_PATHS.has(path);
}

// A deactivated account produces a 403 — the same status as an ordinary
// RBAC denial. The backend disambiguates with an X-Account-Status header;
// the response detail ("...inactif...") is a fallback for setups where a
// proxy strips custom headers.
function isAccountDeactivated(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const res = error.response;
  if (!res || res.status !== 403) return false;
  const header = res.headers?.["x-account-status"];
  if (typeof header === "string" && header.toLowerCase() === "deactivated") {
    return true;
  }
  const detail = (res.data as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" && /inactif|inactive/i.test(detail);
}

// Tear the session down and tell the user why. `forceLogout` clears the
// auth store, purges the query cache, and redirects to /login — so the UI
// does not linger on a stale authenticated screen. The fixed toast id
// dedupes the burst of parallel 403s a deactivated session fires off.
function handleAccountDeactivated(): void {
  forceLogout();
  toast.error(ACCOUNT_DEACTIVATED_MESSAGE, {
    id: "account-deactivated",
    duration: 10_000,
  });
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetryableRequest | undefined;
    const status = error.response?.status;

    // Account deactivated mid-session. Skip /auth/* — the login page
    // renders its own inactive-account notice on a failed sign-in.
    if (isAccountDeactivated(error) && !isRefreshExempt(original?.url)) {
      handleAccountDeactivated();
      return Promise.reject(error);
    }

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
      // A refresh rejected because the account was deactivated gets the
      // explicit notice; any other failure is a plain session expiry.
      // Either way `forceLogout` clears the cache and redirects to /login.
      if (isAccountDeactivated(refreshErr)) {
        handleAccountDeactivated();
      } else {
        forceLogout();
      }
      return Promise.reject(refreshErr);
    }
  },
);

// Module-level cache for the bootstrap result. React StrictMode mounts
// effects twice in dev, which without this guard would fire two parallel
// /auth/refresh requests. The second one finds the first one's jti
// already consumed, hits the reuse-detection branch in the store and
// wipes the entire family — leaving the user logged out on the next
// page reload. Caching the promise turns the second call into a no-op.
let bootstrapPromise: Promise<boolean> | null = null;

/**
 * Was the bootstrap failure transient (worth retrying) or definitive?
 *
 * A network error or a 5xx means the backend was momentarily unreachable —
 * caching that as "not authenticated" would freeze the user on /login even
 * after the backend recovers, until a full browser reload. A 4xx (notably
 * 401) is a real answer: the refresh cookie is absent or invalid.
 */
function isTransientFailure(err: unknown): boolean {
  if (!axios.isAxiosError(err)) return true; // non-Axios throw — treat as transient
  const status = err.response?.status;
  if (status === undefined) return true; // no response at all — network error
  return status >= 500;
}

export function bootstrapAuth(): Promise<boolean> {
  if (bootstrapPromise === null) {
    bootstrapPromise = (async () => {
      try {
        await runRefresh();
        return true;
      } catch (err) {
        // A reload after deactivation lands here — surface the same notice
        // the in-session path shows instead of a silent bounce to /login.
        if (isAccountDeactivated(err)) {
          handleAccountDeactivated();
          return false;
        }
        // A transient failure (backend briefly down) must NOT be cached:
        // drop the memoized promise so a later call retries the refresh
        // once the backend is healthy again. A definitive 4xx stays cached.
        if (isTransientFailure(err)) {
          bootstrapPromise = null;
          return false;
        }
        // Definitive unauthenticated (4xx): clear any stale token. No
        // imperative navigation here — this runs at app boot before the
        // router mounts; `AuthGate` renders /login once bootstrap settles.
        clearSession();
        return false;
      }
    })();
  }
  return bootstrapPromise;
}
