import { useRef } from "react";
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
 * fetch deltas only.
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
  const eventsRef = useRef<MigrationEventResponse[]>([]);
  const intervalRef = useRef<number | null>(null);

  const query = useQuery({
    queryKey: ["migration", migrationId, "events"],
    queryFn: async ({ signal }) => {
      const page = await fetchMigrationEvents(migrationId, {
        sinceSequenceId: sinceRef.current,
        limit: 200,
        signal,
      });
      if (page.items.length > 0) {
        eventsRef.current = [...eventsRef.current, ...page.items];
        sinceRef.current = page.next_since_sequence_id ?? sinceRef.current;
      }
      return page;
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

  const events = eventsRef.current;
  const isLoading = query.isPending && events.length === 0;

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

      {!isLoading && events.length === 0 && (
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
