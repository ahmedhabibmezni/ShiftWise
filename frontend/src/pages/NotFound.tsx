/**
 * Catch-all 404 page for the `*` route. Lives in its own module so
 * `routes.tsx` exports only the `router` object — keeping Vite's fast-refresh
 * boundary clean (a file may not mix component and non-component exports).
 */
export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="glass-card max-w-md p-6">
        <div className="kicker mb-2">404 · Page Not Found</div>
        <p className="mt-2 text-[13px] text-[var(--text-secondary)]">
          That page does not exist. It may have moved, or the link is wrong.{" "}
          <a
            href="/"
            className="text-[var(--accent-light)] hover:text-[var(--accent-primary)] font-bold"
          >
            Go to dashboard →
          </a>
        </p>
      </div>
    </div>
  );
}
