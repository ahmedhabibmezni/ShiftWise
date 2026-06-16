import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  ArrowDown,
  CircleDashed,
  HeartPulse,
  type LucideIcon,
} from "lucide-react";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchMigrationEvents,
  type MigrationEventResponse,
  type MigrationEventType,
  type MigrationStatus,
} from "@/api/migrations";
import {
  nextAdaptiveInterval,
  TERMINAL_MIGRATION_STATUSES,
} from "@/lib/adaptivePolling";
import { formatRelativeTime } from "@/lib/format";

/**
 * Vertical chronological timeline of migration audit events (US1).
 *
 * Polls `GET /api/v1/migrations/:id/events` via TanStack Query with an
 * adaptive `refetchInterval`. The polling cadence starts at 2 s after an
 * observed event and decays toward 15 s while the migration sits in the
 * same status. Polling stops as soon as the migration reaches a terminal
 * status. The cursor (`since_sequence_id`) is held in a ref so refetches
 * fetch deltas only; the accumulated event list lives in `useState` so
 * appending a delta triggers a React re-render (a ref-only accumulator
 * silently dropped frames during steady-state delta polls).
 *
 * Ordering follows `sequence_id` ASC — never `created_at` — because Q2
 * pinned that as the canonical ordering primitive for the audit log.
 */
export function MigrationTimeline({
  migrationId,
  status,
}: {
  migrationId: number;
  status: MigrationStatus;
}) {
  const sinceRef = useRef<number>(0);
  const intervalRef = useRef<number | null>(null);
  const [events, setEvents] = useState<MigrationEventResponse[]>([]);

  // Reset cursor + accumulator when the component is reused across
  // migrations (drawer navigation). Without this, a new migration's
  // first poll would carry the previous migration's
  // `since_sequence_id` and the new event list would be prefixed by
  // stale rows from the old timeline.
  useEffect(() => {
    sinceRef.current = 0;
    intervalRef.current = null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional cross-migration accumulator reset; clearing on the migrationId change is the whole point of this effect.
    setEvents([]);
  }, [migrationId]);

  const query = useQuery({
    queryKey: ["migration", migrationId, "events"],
    queryFn: async ({ signal }) => {
      return fetchMigrationEvents(migrationId, {
        sinceSequenceId: sinceRef.current,
        limit: 200,
        signal,
      });
    },
    refetchInterval: (q) => {
      const data = q.state.data;
      const observed = (data?.items.length ?? 0) > 0;
      const nextMs = nextAdaptiveInterval({
        status,
        observedNewEvent: observed,
        prevInterval: intervalRef.current,
      });
      intervalRef.current = nextMs === false ? null : nextMs;
      return nextMs;
    },
  });

  // Append-on-fetch effect — merges every successful delta into the
  // accumulator state. Deduping by sequence_id makes the merge idempotent
  // so a duplicate refetch (refocus / network retry) never doubles up.
  useEffect(() => {
    const page = query.data;
    if (!page || page.items.length === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- merging each polled delta into the accumulator is an external-system sync (paginated audit feed); a ref-only accumulator silently dropped frames (see component header).
    setEvents((prev) => {
      const known = new Set(prev.map((e) => e.sequence_id));
      const fresh = page.items.filter((e) => !known.has(e.sequence_id));
      return fresh.length > 0 ? [...prev, ...fresh] : prev;
    });
    sinceRef.current = page.next_since_sequence_id ?? sinceRef.current;
  }, [query.data]);

  const isLoading = query.isPending && events.length === 0;
  const isError = query.isError && events.length === 0;

  return (
    <section data-testid="migration-timeline">
      <div className="flex items-center gap-2 mb-3">
        <Icon icon={ArrowDown} size={14} className="text-[var(--text-muted)]" />
        <span className="kicker">Audit timeline</span>
        {!TERMINAL_MIGRATION_STATUSES.has(status) && (
          <span className="text-[10px] uppercase tracking-[0.04em] font-medium text-[var(--text-muted)]">
            · live
          </span>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {isError && (
        <div
          role="alert"
          data-testid="timeline-error"
          className="rounded-xl bg-[var(--surface-soft)] p-4 text-[13px]"
          style={{ color: "var(--alert-critical)" }}
        >
          <span className="font-medium">Failed to load timeline.</span>{" "}
          <button
            type="button"
            onClick={() => query.refetch()}
            className="underline"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && events.length === 0 && (
        <div className="rounded-xl bg-[var(--surface-soft)] p-4 text-[13px] text-[var(--text-muted)]">
          No events recorded yet for this migration.
        </div>
      )}

      {events.length > 0 && (
        <ol className="space-y-2" data-testid="timeline-list">
          {events.map((event) => (
            <TimelineRow key={event.id} event={event} />
          ))}
        </ol>
      )}
    </section>
  );
}

const EVENT_ICON: Record<MigrationEventType, LucideIcon> = {
  state_transition: ArrowDown,
  stage_event: CircleDashed,
  classified_error: AlertOctagon,
  heartbeat: HeartPulse,
};

const EVENT_TONE: Record<MigrationEventType, string> = {
  state_transition: "var(--text-primary)",
  stage_event: "var(--text-secondary)",
  classified_error: "var(--alert-critical)",
  heartbeat: "var(--text-muted)",
};

function TimelineRow({ event }: { event: MigrationEventResponse }) {
  const EventIcon = EVENT_ICON[event.event_type];
  const color = EVENT_TONE[event.event_type];

  const headline =
    event.event_type === "state_transition"
      ? `${event.from_status ?? "—"} → ${event.to_status ?? "—"}`
      : event.event_type === "classified_error"
        ? `Error · ${
            (event.payload?.error_code as string | undefined) ?? "unclassified"
          }`
        : event.event_type === "heartbeat"
          ? `Heartbeat · ${event.to_status ?? "—"}`
          : (event.message ?? `Stage event · ${event.to_status ?? "—"}`);

  return (
    <li
      data-testid="timeline-row"
      data-event-type={event.event_type}
      data-sequence-id={event.sequence_id}
      className="flex items-start gap-3 rounded-xl bg-[var(--surface-soft)] p-3"
    >
      <EventIcon size={14} className="mt-[3px]" style={{ color }} />
      <div className="min-w-0 flex-1">
        <div
          className="text-[13px] font-medium"
          style={{ color }}
        >
          {headline}
        </div>
        {event.message && event.event_type !== "stage_event" && (
          <div className="text-[12px] text-[var(--text-muted)] break-words mt-0.5">
            {event.message}
          </div>
        )}
        <div
          className="text-[10px] uppercase tracking-[0.04em] font-medium text-[var(--text-muted)] mt-0.5"
          title={new Date(event.created_at).toISOString()}
        >
          seq #{event.sequence_id} · {formatRelativeTime(event.created_at)} · {event.actor_type}
        </div>
      </div>
    </li>
  );
}
