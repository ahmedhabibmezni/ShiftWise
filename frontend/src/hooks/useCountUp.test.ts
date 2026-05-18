import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCountUp } from "./useCountUp";

// F22 — CountUp must animate only on the FIRST data load (0 -> real count
// when a query resolves), not re-fire its 600ms animation on every 30s
// poll refetch that shifts the displayed value.

describe("useCountUp — first-load-only animation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function flushAnimation() {
    // Advance rAF callbacks past the animation duration.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
  }

  it("animates the first time the target changes (the data-load transition)", () => {
    // Mount at 0 (query pending), then the query resolves to 120.
    const { result, rerender } = renderHook(({ t }) => useCountUp(t, 600), {
      initialProps: { t: 0 },
    });
    expect(result.current).toBe(0);

    rerender({ t: 120 });
    // Mid-animation the value is between the start and the target.
    expect(result.current).toBeGreaterThanOrEqual(0);
    expect(result.current).toBeLessThanOrEqual(120);

    flushAnimation();
    expect(result.current).toBe(120);
  });

  it("does NOT re-animate on a later target change (poll refetch)", () => {
    const { result, rerender } = renderHook(({ t }) => useCountUp(t, 600), {
      initialProps: { t: 0 },
    });

    // First load: 0 -> 120, animates and settles.
    rerender({ t: 120 });
    flushAnimation();
    expect(result.current).toBe(120);

    // A poll refetch shifts the count to 121. This must NOT animate —
    // the value snaps straight to the new target.
    rerender({ t: 121 });
    expect(result.current).toBe(121);

    // And again.
    rerender({ t: 130 });
    expect(result.current).toBe(130);
  });
});
