import {
  Home,
  Server,
  ArrowLeftRight,
  Network,
  AlertTriangle,
  FileBarChart,
  Settings as SettingsIcon,
  ChevronUp,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

type NavItem = { id: string; label: string; icon: LucideIcon; badge?: number };

const ITEMS: NavItem[] = [
  { id: "overview", label: "overview", icon: Home },
  { id: "hypervisors", label: "hypervisors", icon: Server },
  { id: "migrations", label: "migrations", icon: ArrowLeftRight },
  { id: "infrastructure", label: "infrastructure", icon: Network },
  { id: "alerts", label: "alerts", icon: AlertTriangle, badge: 12 },
  { id: "reports", label: "reports", icon: FileBarChart },
  { id: "settings", label: "settings", icon: SettingsIcon },
];

export function Sidebar({ active = "overview" }: { active?: string }) {
  return (
    <aside
      aria-label="Navigation principale"
      className="w-20 shrink-0 bg-bg-elev border-r border-line-strong flex flex-col"
    >
      <div className="h-16 w-full flex items-center justify-center border-b border-line">
        <div className="font-mono uppercase font-bold text-[20px] tracking-[0.04em] text-ink">
          SW
        </div>
      </div>

      <nav className="flex-1 py-2">
        <ul>
          {ITEMS.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                aria-current={item.id === active ? "page" : undefined}
                className={cn(
                  "relative w-full h-16 flex flex-col items-center justify-center gap-1.5 transition-colors duration-150",
                  item.id === active
                    ? "text-signal"
                    : "text-ink-muted hover:bg-bg-elev-2 hover:text-ink",
                )}
              >
                {item.id === active && (
                  <span
                    aria-hidden
                    className="absolute left-0 top-2 bottom-2 w-0.5 bg-signal"
                  />
                )}
                <span className="relative">
                  <Icon icon={item.icon} size={20} />
                  {item.badge && (
                    <span
                      className="absolute -top-1.5 -right-2.5 min-w-[18px] h-[18px] px-1 rounded-full bg-signal text-signal-ink font-mono text-[10px] font-medium tabular flex items-center justify-center"
                      aria-label={`${item.badge} alertes`}
                    >
                      {item.badge}
                    </span>
                  )}
                </span>
                <span className="font-mono text-[10px] uppercase tracking-[0.04em]">
                  {item.label}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <button
        type="button"
        className="h-20 px-3 flex items-center gap-3 border-t border-line hover:bg-bg-elev-2 transition-colors duration-150 text-left"
        aria-label="Profil utilisateur"
      >
        <span
          aria-hidden
          className="h-8 w-8 rounded-sm bg-bg-elev-2 border border-line-strong flex items-center justify-center font-mono text-[12px] font-semibold text-ink"
        >
          AH
        </span>
        <span className="flex-1 min-w-0">
          <span className="block font-mono text-[11px] uppercase text-ink truncate">
            sysop
          </span>
          <span className="block font-mono text-[10px] uppercase text-ink-muted truncate">
            admin
          </span>
        </span>
        <Icon icon={ChevronUp} size={16} className="text-ink-muted" />
      </button>
    </aside>
  );
}
