import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Suspense fallback for lazily-loaded route chunks. Lives in its own module so
 * `routes.tsx` stays a pure router-config export (react-refresh requires a file
 * to export only components for fast refresh to work).
 */
export function RouteFallback() {
  return (
    <div className="flex flex-col gap-4 p-6" aria-busy="true" aria-label="Loading page">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}
