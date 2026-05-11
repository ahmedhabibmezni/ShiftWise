import { cn } from "@/lib/cn";

export function Skeleton({
  className,
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      aria-hidden
      className={cn("sw-skel rounded-sm", className)}
      style={style}
    />
  );
}

export function SkeletonRow({ cols = 4 }: { cols?: number }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-line last:border-b-0">
      {Array.from({ length: cols }, (_, i) => (
        <Skeleton
          key={i}
          className="h-3 flex-1"
          style={{ maxWidth: i === 0 ? "30%" : i === cols - 1 ? "12%" : "20%" }}
        />
      ))}
    </div>
  );
}

export function SkeletonStat({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const h = size === "lg" ? "h-12" : size === "md" ? "h-8" : "h-5";
  return (
    <div className="space-y-2">
      <Skeleton className="h-2.5 w-20" />
      <Skeleton className={cn(h, "w-32")} />
    </div>
  );
}
