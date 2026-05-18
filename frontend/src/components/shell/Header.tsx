import { useEffect, useState } from "react";
import { Menu, Search, Settings as SettingsIcon } from "lucide-react";
import { Icon } from "@/components/ui/Icon";
import { Kbd } from "@/components/ui/Kbd";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useAuthStore } from "@/store/auth";
import { Link } from "react-router-dom";

export function Header({
  title = "Dashboard",
  parent = "Pages",
  onMenuClick,
}: {
  title?: string;
  parent?: string;
  /** Opens the mobile navigation drawer; only wired below the `lg` breakpoint. */
  onMenuClick?: () => void;
}) {
  const user = useAuthStore((s) => s.user);

  return (
    <header className="flex items-center justify-between gap-4 px-1">
      {/* Left: menu trigger (mobile) + breadcrumbs + page title */}
      <div className="flex items-center gap-2 min-w-0">
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open navigation"
          className="lg:hidden shrink-0 -ml-1.5 h-11 w-11 inline-flex items-center justify-center rounded-xl text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-soft)] transition-colors duration-200"
        >
          <Icon icon={Menu} size={20} strokeWidth={1.85} />
        </button>
        <div className="flex flex-col gap-1 min-w-0">
          <div className="text-[12px] text-[var(--text-secondary)] font-medium">
            {parent}
            <span className="mx-2 opacity-50">/</span>
            <span className="text-[var(--text-primary)] font-bold">{title}</span>
          </div>
          <div className="text-[16px] font-bold text-[var(--text-primary)] tracking-[-0.005em]">
            {title}
          </div>
        </div>
      </div>

      {/* Right: search · live · settings · theme · profile */}
      <div className="flex items-center gap-3 shrink-0">
        <button
          type="button"
          aria-label="Open command palette"
          onClick={() =>
            window.dispatchEvent(new CustomEvent("shiftwise:open-cmdk"))
          }
          className="hidden md:inline-flex glass-card items-center gap-2.5 pl-3.5 pr-3 h-9 rounded-[14px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors duration-200 w-[280px]"
        >
          <Icon icon={Search} size={14} className="text-[var(--text-muted)]" />
          <span className="text-[13px] flex-1 min-w-0 text-left truncate">
            Search or jump to…
          </span>
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
        </button>

        <span className="hidden xl:flex items-center gap-2.5 text-[12px]">
          <LiveIndicator label={null} tone="ok" srLabel="System healthy" />
          <Clock />
        </span>

        {user && (
          <Link
            to="/settings"
            className="hidden md:inline-flex items-center gap-2 text-[13px] font-semibold text-[var(--text-secondary)] hover:text-[var(--accent-light)] transition-colors duration-200"
          >
            <Icon icon={SettingsIcon} size={14} />
            <span className="truncate max-w-[120px]">{user.username}</span>
          </Link>
        )}

        <ThemeToggle />
      </div>
    </header>
  );
}

function formatTime(d: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

/**
 * Live UTC clock. Isolated as its own component so the per-second `setState`
 * tick re-renders only this `<span>`, not the whole AppLayout shell.
 */
function Clock() {
  const [now, setNow] = useState(() => formatTime(new Date()));
  useEffect(() => {
    const id = window.setInterval(() => setNow(formatTime(new Date())), 1_000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="tabular text-[var(--text-muted)] font-medium">{now}</span>
  );
}
