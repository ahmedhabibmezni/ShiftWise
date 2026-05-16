import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

const DEFAULT_DURATION = 600;

/** ease-out-expo — confident deceleration, no overshoot (DESIGN.md motion curve). */
function easeOutExpo(t: number): number {
  return t >= 1 ? 1 : 1 - 2 ** (-10 * t);
}

/**
 * Animates a number from its current displayed value to `target` over
 * `duration` ms. Returns the in-flight value; callers format it for display.
 *
 * - Animates on `target` change, not on first mount — the initial render
 *   shows `target` directly. The dashboard's "data lands" count-up still
 *   fires because a metric genuinely changes (0 -> real) when a query
 *   resolves, and a poll refetch that shifts the value re-triggers it.
 * - Honours `prefers-reduced-motion`: returns `target` verbatim, no animation.
 */
export function useCountUp(
  target: number,
  duration: number = DEFAULT_DURATION,
): number {
  const reducedMotion = usePrefersReducedMotion();
  const [value, setValue] = useState(target);
  // Latest painted value — written by the rAF loop, never during render.
  const valueRef = useRef(target);
  // Last `target` the rAF loop acted on, to detect real changes.
  const targetRef = useRef(target);
  const frameRef = useRef<number | null>(null);
  const animate = !reducedMotion && Number.isFinite(target);

  useEffect(() => {
    // Reduced motion / non-finite input: render returns `target` directly,
    // so the effect has nothing to drive.
    if (!animate) return;
    if (targetRef.current === target) return;
    targetRef.current = target;

    const from = Number.isFinite(valueRef.current) ? valueRef.current : target;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const next = from + (target - from) * easeOutExpo(t);
      valueRef.current = next;
      setValue(next);
      if (t < 1) frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [target, duration, animate]);

  return animate ? value : target;
}
