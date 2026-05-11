import { Search } from "lucide-react";
import { Icon } from "@/components/ui/Icon";
import { Kbd } from "@/components/ui/Kbd";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { usePrimaryRole } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";

export function Header({
  title = "overview",
  timestamp = "14:22:01 UTC",
}: {
  title?: string;
  timestamp?: string;
}) {
  const role = usePrimaryRole();
  const user = useAuthStore((s) => s.user);
  return (
    <header className="h-14 px-6 flex items-center justify-between border-b border-line bg-bg/95 backdrop-blur-sm sticky top-0 z-30">
      <div className="flex items-center gap-4 min-w-0">
        <nav aria-label="Breadcrumb" className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
          <span className="text-ink-faint">/</span>
          <span className="text-ink">{title}</span>
        </nav>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label="Open command palette"
          onClick={() =>
            window.dispatchEvent(new CustomEvent("shiftwise:open-cmdk"))
          }
          className="hidden md:inline-flex h-9 items-center gap-3 pl-3 pr-2 border border-line bg-bg-elev hover:bg-bg-elev-2 hover:border-line-strong rounded-sm text-ink-muted hover:text-ink transition-colors duration-150 focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-1"
        >
          <Icon icon={Search} size={14} />
          <span className="font-mono text-[12px] text-ink-faint">search…</span>
          <span className="ml-6 flex items-center gap-1">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>

        <span className="hidden lg:flex items-center gap-3 px-3 h-9 border border-line rounded-sm bg-bg-elev">
          <LiveIndicator label="live" />
          <span className="h-3.5 w-px bg-line" />
          <span className="font-mono text-[11px] tabular text-ink-muted">{timestamp}</span>
        </span>

        {user && (
          <span
            className="hidden md:inline-flex items-center gap-2 h-9 pl-2 pr-3 border border-line rounded-sm bg-bg-elev"
            aria-label="Signed-in user"
          >
            <RoleBadge role={role} />
            <span className="h-3.5 w-px bg-line" />
            <span className="font-mono text-[11px] tabular text-ink-muted truncate max-w-[160px]">
              {user.username}
            </span>
          </span>
        )}

        <ThemeToggle />
      </div>
    </header>
  );
}
