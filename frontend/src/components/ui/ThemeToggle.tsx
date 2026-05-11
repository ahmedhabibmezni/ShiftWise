import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { Icon } from "./Icon";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className="h-10 w-10 inline-flex items-center justify-center rounded-sm border border-transparent text-ink-muted hover:bg-bg-elev hover:text-ink transition-colors duration-150 focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-1"
    >
      <Icon icon={theme === "dark" ? Sun : Moon} size={20} />
    </button>
  );
}
