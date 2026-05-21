import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/msw/server";
import { MigrationTimeline } from "@/pages/MigrationTimeline";
import type { MigrationEventListResponse } from "@/api/migrations";

function makeResponse(
  items: MigrationEventListResponse["items"],
  hasMore = false,
): MigrationEventListResponse {
  return {
    items,
    total: items.length,
    next_since_sequence_id: items.length > 0 ? items[items.length - 1].sequence_id : null,
    has_more: hasMore,
  };
}

function renderTimeline(args: { migrationId: number; status: Parameters<typeof MigrationTimeline>[0]["status"] }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MigrationTimeline {...args} />
    </QueryClientProvider>,
  );
}

const SAMPLE_EVENTS: MigrationEventListResponse["items"] = [
  {
    id: 1,
    migration_id: 42,
    tenant_id: "t1",
    sequence_id: 1,
    event_type: "state_transition",
    from_status: null,
    to_status: "pending",
    actor_id: null,
    actor_type: "system",
    message: "Migration created",
    payload: null,
    created_at: "2026-05-21T01:00:00Z",
  },
  {
    id: 2,
    migration_id: 42,
    tenant_id: "t1",
    sequence_id: 2,
    event_type: "state_transition",
    from_status: "pending",
    to_status: "validating",
    actor_id: null,
    actor_type: "worker",
    message: null,
    payload: null,
    created_at: "2026-05-21T01:00:05Z",
  },
  {
    id: 3,
    migration_id: 42,
    tenant_id: "t1",
    sequence_id: 3,
    event_type: "stage_event",
    from_status: null,
    to_status: "transferring",
    actor_id: null,
    actor_type: "worker",
    message: "populator phase started (1 disk(s))",
    payload: null,
    created_at: "2026-05-21T01:00:10Z",
  },
];

describe("MigrationTimeline", () => {
  it("renders events in sequence_id ascending order", async () => {
    server.use(
      http.get("*/api/v1/migrations/42/events", () =>
        HttpResponse.json(makeResponse(SAMPLE_EVENTS)),
      ),
    );

    renderTimeline({ migrationId: 42, status: "transferring" });

    await waitFor(() => {
      const rows = screen.getAllByTestId("timeline-row");
      expect(rows).toHaveLength(3);
    });

    const rows = screen.getAllByTestId("timeline-row");
    const seqs = rows.map((row) => row.getAttribute("data-sequence-id"));
    expect(seqs).toEqual(["1", "2", "3"]);
  });

  it("renders the empty state when no events have been recorded", async () => {
    server.use(
      http.get("*/api/v1/migrations/99/events", () =>
        HttpResponse.json(makeResponse([])),
      ),
    );

    renderTimeline({ migrationId: 99, status: "pending" });

    await waitFor(() => {
      expect(
        screen.getByText(/no events recorded yet/i),
      ).toBeInTheDocument();
    });
  });

  it("renders the live label for non-terminal migrations and hides it on terminal", async () => {
    server.use(
      http.get("*/api/v1/migrations/1/events", () =>
        HttpResponse.json(makeResponse(SAMPLE_EVENTS)),
      ),
    );

    const { rerender } = renderTimeline({
      migrationId: 1,
      status: "transferring",
    });
    await waitFor(() => screen.getAllByTestId("timeline-row"));
    expect(screen.getByText(/· live/i)).toBeInTheDocument();

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    rerender(
      <QueryClientProvider client={client}>
        <MigrationTimeline migrationId={1} status="completed" />
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(screen.queryByText(/· live/i)).not.toBeInTheDocument();
    });
  });

  it("renders an error banner with a Retry button when the fetch fails", async () => {
    server.use(
      http.get("*/api/v1/migrations/500/events", () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
      ),
    );

    renderTimeline({ migrationId: 500, status: "transferring" });

    await waitFor(() => {
      expect(screen.getByTestId("timeline-error")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByText(/no events recorded yet/i)).not.toBeInTheDocument();
  });

  it("renders classified_error rows with the error code in the headline", async () => {
    server.use(
      http.get("*/api/v1/migrations/7/events", () =>
        HttpResponse.json(
          makeResponse([
            {
              id: 10,
              migration_id: 7,
              tenant_id: "t1",
              sequence_id: 1,
              event_type: "classified_error",
              from_status: null,
              to_status: "failed",
              actor_id: null,
              actor_type: "worker",
              message: "K8s API timed out",
              payload: { error_code: "ERR_MIG_K8S_TIMEOUT" },
              created_at: "2026-05-21T01:00:00Z",
            },
          ]),
        ),
      ),
    );

    renderTimeline({ migrationId: 7, status: "failed" });

    await waitFor(() => {
      expect(
        screen.getByText(/error · ERR_MIG_K8S_TIMEOUT/i),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/K8s API timed out/i)).toBeInTheDocument();
  });
});
