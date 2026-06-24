import { useEffect, type ReactNode } from "react";
import { BrandMark } from "@/components/ui/Logo";
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
    <div className="min-h-[100dvh] flex flex-col items-center justify-center gap-4">
      <BrandMark
        className="w-24 h-24"
        style={{ animation: "shiftwise-pulse 1.6s var(--ease-out) infinite" }}
      />
      <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-[var(--text-secondary)]">
        ShiftWise · Initializing
      </div>
    </div>
  );
}
