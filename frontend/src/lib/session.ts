import { clearSession } from "@/store/auth";
import { queryClient } from "@/lib/queryClient";

/**
 * Session teardown — the single path every "the session is over" caller
 * must funnel through.
 *
 * Three things have to happen atomically when a session ends, and before
 * this helper existed they were scattered:
 *
 *  1. **Auth store** — drop the in-memory access token and user object so
 *     route guards re-evaluate as anonymous.
 *  2. **Query cache** — `queryClient.clear()`. TanStack Query keeps the
 *     previous tenant's VMs / migrations / stats in memory; without this a
 *     same-tab account switch (logout → login as another user) flashes the
 *     old tenant's data for up to one `staleTime` window. Clearing the cache
 *     closes that cross-tenant leak.
 *  3. **Navigation** — imperatively route to `/login`. The axios interceptor
 *     runs outside React, so it cannot rely on a guard re-render alone; a
 *     stale authenticated screen would otherwise linger until the next
 *     user interaction.
 *
 * Navigation is delegated through a registered callback rather than a direct
 * `router` import: `lib/session` is pulled in by `lib/axios`, and importing
 * the router (which imports every page, which imports axios) would form an
 * initialization cycle. `main.tsx` registers the navigator once at startup.
 */

type Navigator = (path: string) => void;

let navigate: Navigator | null = null;

/**
 * Wire up the imperative navigator. Called once from `main.tsx` with the
 * router instance. Until this runs, `forceLogout` still clears state — it
 * just cannot redirect (only relevant for the pre-mount window).
 */
export function registerSessionNavigator(fn: Navigator): void {
  navigate = fn;
}

/**
 * Tear the session down: clear the auth store, purge the query cache, and
 * redirect to `/login`. Safe to call repeatedly — clearing already-empty
 * state is a no-op.
 */
export function forceLogout(): void {
  clearSession();
  queryClient.clear();
  navigate?.("/login");
}
