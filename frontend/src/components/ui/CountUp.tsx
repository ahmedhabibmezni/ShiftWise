import { useCountUp } from "@/hooks/useCountUp";

const DEFAULT_FORMAT = (n: number): string =>
  Math.round(n).toLocaleString("en-US");

/**
 * Renders a number that animates to its value (DESIGN.md: count-up on
 * mount/update). Drop-in for any `ReactNode` value slot — KPI cards, gauges,
 * fleet stats. Non-numeric input renders `fallback` with no animation.
 */
export function CountUp({
  value,
  duration,
  format = DEFAULT_FORMAT,
  fallback = "—",
}: {
  value: number | null | undefined;
  duration?: number;
  format?: (n: number) => string;
  fallback?: string;
}) {
  const isNumber = typeof value === "number" && Number.isFinite(value);
  const current = useCountUp(isNumber ? value : 0, duration);
  return <>{isNumber ? format(current) : fallback}</>;
}
