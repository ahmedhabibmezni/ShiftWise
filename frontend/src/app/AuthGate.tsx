import { useEffect, type ReactNode } from "react";
import { bootstrapAuth } from "@/lib/axios";
import { fetchCurrentUser } from "@/api/auth";
import { useAuthStore } from "@/store/auth";

type Props = { children: ReactNode };

export function AuthGate({ children }: Props) {
  const bootstrapped = useAuthStore((s) => s.bootstrapped);
  const setUser = useAuthStore((s) => s.setUser);
  const markBootstrapped = useAuthStore((s) => s.markBootstrapped);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const authenticated = await bootstrapAuth();
      if (authenticated && !cancelled) {
        try {
          const me = await fetchCurrentUser();
          if (!cancelled) setUser(me);
        } catch {
          // /me failed even though refresh succeeded — treat as anonymous.
        }
      }
      if (!cancelled) markBootstrapped();
    })();
    return () => {
      cancelled = true;
    };
  }, [setUser, markBootstrapped]);

  if (!bootstrapped) return <BootSplash />;
  return <>{children}</>;
}

function BootSplash() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg text-ink-muted">
      <div className="font-mono text-[11px] uppercase tracking-[0.06em]">
        SW · INITIALISATION
      </div>
    </div>
  );
}
