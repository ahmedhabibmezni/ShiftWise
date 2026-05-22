/**
 * Adaptive polling cadence for the migration timeline (US1, Q4).
 *
 * The migration pipeline emits at two distinct rhythms:
 *   - **Fast** during stage transitions (sub-second between state_transition
 *     and stage_event rows).
 *   - **Slow** during long stages (heartbeat every ~30 s while TRANSFERRING).
 *
 * A fixed-interval poll wastes traffic during heartbeats yet lags fast
 * transitions. The adaptive cadence below starts at 2000 ms after a new
 * event is observed and decays toward 15 000 ms while the migration stays
 * in the same state. On a terminal status the function returns `false`,
 * which TanStack Query interprets as "stop polling".
 */
import type { MigrationStatus } from "@/api/migrations";

/** Statuses where the pipeline has stopped emitting events. */
export const TERMINAL_MIGRATION_STATUSES: ReadonlySet<MigrationStatus> = new Set(
  ["completed", "failed", "cancelled", "rolled_back"],
);

/**
 * Every MigrationStatus value the backend is allowed to emit (from the
 * SQLAlchemy enum). The list lets us detect a status the frontend has no
 * mapping for — typo, new enum value forgotten in a deploy, lowercase
 * mismatch — and surface it as a console warning instead of silently
 * polling forever at the cap.
 */
const KNOWN_MIGRATION_STATUSES: ReadonlySet<MigrationStatus> = new Set([
  "pending",
  "validating",
  "preparing",
  "transferring",
  "configuring",
  "starting",
  "verifying",
  "completed",
  "failed",
  "cancelled",
  "rollback",
  "rolled_back",
]);

/** Initial cadence right after a transition is observed (ms). */
export const INITIAL_POLL_MS = 2000;

/** Upper bound the cadence decays toward (ms). */
export const MAX_POLL_MS = 15000;

/** Multiplier applied each time the same status is observed twice. */
export const DECAY_FACTOR = 1.5;

export type AdaptivePollingInput = {
  /** The migration's current status, as reported by the latest response. */
  status: MigrationStatus;
  /** True iff at least one new event was returned by the latest fetch. */
  observedNewEvent: boolean;
  /** Previous interval value, or `null` on the first call. */
  prevInterval: number | null;
};

/**
 * Compute the next refetch interval for the timeline poll.
 *
 * Returns `false` once the migration has reached a terminal status; the
 * caller uses that to tell TanStack Query to stop polling entirely.
 */
export function nextAdaptiveInterval(
  input: AdaptivePollingInput,
): number | false {
  if (TERMINAL_MIGRATION_STATUSES.has(input.status)) {
    return false;
  }
  if (!KNOWN_MIGRATION_STATUSES.has(input.status)) {
    // Surface backend / frontend drift loudly. The poll falls through to
    // the standard decay (INITIAL_POLL_MS on a fresh state, decaying
    // toward MAX_POLL_MS) so a typo never silently freezes the UI.
    // eslint-disable-next-line no-console
    console.warn(
      `nextAdaptiveInterval: unknown migration status ${JSON.stringify(
        input.status,
      )} - polling continues at the standard adaptive cadence (` +
        `${INITIAL_POLL_MS}ms initial, decaying toward ${MAX_POLL_MS}ms); ` +
        `check MigrationStatus enum sync`,
    );
  }
  if (input.prevInterval == null || input.observedNewEvent) {
    return INITIAL_POLL_MS;
  }
  return Math.min(Math.round(input.prevInterval * DECAY_FACTOR), MAX_POLL_MS);
}
