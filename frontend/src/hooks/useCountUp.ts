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
 * - **Animates only the first `target` change** — the data-load transition
 *   (`0` while the query is pending → the real count when it resolves).
 *   Dashboard KPIs poll every 30s; without this guard each refetch that
 *   nudged the value would re-fire the 600ms count-up, producing a
 *   distracting flicker on an otherwise static dashboard (F22). Once the
 *   first tween has settled, the hook returns every later `target` verbatim.
 * - The initial render shows `target` directly (no mount animation).
 * - Honours `prefers-reduced-motion`: returns `target` verbatim, no animation.
 */
export function useCountUp(
  target: number,
  duration: number = DEFAULT_DURATION,
): number {
  const reducedMotion = usePrefersReducedMotion();
  const [value, setValue] = useState(target);
  // Flips true when the first tween finishes. From then on the hook returns
  // `target` directly, so a poll refetch needs no state write to stay current
  // — which also keeps the snap out of the effect body (no cascading render).
  const [settled, setSettled] = useState(false);
  // Latest painted value — written by the rAF loop, never during render.
  const valueRef = useRef(target);
  // Last `target` the rAF loop acted on, to detect real changes.
  const targetRef = useRef(target);
  // True once the first target change has started animating — guards against
  // a second change re-triggering the tween while it is still in flight.
  const hasAnimatedRef = useRef(false);
  const frameRef = useRef<number | null>(null);
  const animate = !reducedMotion && Number.isFinite(target);

  useEffect(() => {
    // Reduced motion / non-finite input: render returns `target` directly,
    // so the effect has nothing to drive.
    if (!animate) return;
    if (targetRef.current === target) return;
    targetRef.current = target;

    // Only the first transition animates. A later change (a 30s poll that
    // shifts the count) needs no work here — once `settled` is set the
    // render path returns `target` verbatim, so the value is already current.
    if (hasAnimatedRef.current) return;
    hasAnimatedRef.current = true;

    const from = Number.isFinite(valueRef.current) ? valueRef.current : target;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const next = from + (target - from) * easeOutExpo(t);
      valueRef.current = next;
      setValue(next);
      if (t < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        setSettled(true);
      }
    };
    frameRef.current = requestAnimationFrame(tick);

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [target, duration, animate]);

  // Before and during the first tween, return the in-flight `value`; once it
  // has settled, `target` is authoritative — every later change snaps to it.
  return animate && !settled ? value : target;
}
