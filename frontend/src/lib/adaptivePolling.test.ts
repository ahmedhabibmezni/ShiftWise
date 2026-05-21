/**
 * Unit tests for the adaptive polling cadence (US1, Q4).
 *
 * Pure function tests — no React, no DOM. They pin down the three rules
 * from research § R3:
 *   1. Initial cadence is 2000 ms.
 *   2. Each tick without a new event multiplies the interval by 1.5,
 *      capped at 15 000 ms.
 *   3. A terminal status returns `false` so the client stops polling.
 */
import { describe, expect, it } from "vitest";
import {
  INITIAL_POLL_MS,
  MAX_POLL_MS,
  nextAdaptiveInterval,
  TERMINAL_MIGRATION_STATUSES,
} from "@/lib/adaptivePolling";

describe("nextAdaptiveInterval", () => {
  it("returns 2000ms on the first call (no prevInterval)", () => {
    expect(
      nextAdaptiveInterval({
        status: "transferring",
        observedNewEvent: false,
        prevInterval: null,
      }),
    ).toBe(INITIAL_POLL_MS);
  });

  it("resets to 2000ms when a new event is observed", () => {
    expect(
      nextAdaptiveInterval({
        status: "transferring",
        observedNewEvent: true,
        prevInterval: 10000,
      }),
    ).toBe(INITIAL_POLL_MS);
  });

  it("decays the interval by 1.5x while the migration stays in the same state", () => {
    let interval = nextAdaptiveInterval({
      status: "transferring",
      observedNewEvent: false,
      prevInterval: null,
    }) as number;
    expect(interval).toBe(2000);

    interval = nextAdaptiveInterval({
      status: "transferring",
      observedNewEvent: false,
      prevInterval: interval,
    }) as number;
    expect(interval).toBe(3000);

    interval = nextAdaptiveInterval({
      status: "transferring",
      observedNewEvent: false,
      prevInterval: interval,
    }) as number;
    expect(interval).toBe(4500);
  });

  it("caps the interval at 15000ms no matter how long the migration sits", () => {
    let interval: number | false = 10000;
    for (let i = 0; i < 20; i++) {
      interval = nextAdaptiveInterval({
        status: "transferring",
        observedNewEvent: false,
        prevInterval: interval as number,
      });
      if (interval === false) break;
    }
    expect(interval).toBe(MAX_POLL_MS);
  });

  it.each([
    ["completed"],
    ["failed"],
    ["cancelled"],
    ["rolled_back"],
  ] as const)(
    "returns false (stop polling) once the migration reaches %s",
    (terminal) => {
      expect(
        nextAdaptiveInterval({
          status: terminal,
          observedNewEvent: false,
          prevInterval: 5000,
        }),
      ).toBe(false);
    },
  );

  it("declares the terminal-status set covering all four MigrationStatus terminals", () => {
    expect(TERMINAL_MIGRATION_STATUSES).toEqual(
      new Set(["completed", "failed", "cancelled", "rolled_back"]),
    );
  });
});
