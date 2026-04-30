import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { Icon } from "./Icon";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Activer le thème clair" : "Activer le thème sombre"}
      className="h-8 w-8 inline-flex items-center justify-center border border-line rounded-sm
                 bg-bg text-ink-muted hover:text-ink hover:bg-bg-elev
                 transition-[background-color,color]
                 focus:outline-none focus-visible:outline focus-visible:outline-1
                 focus-visible:outline-signal focus-visible:outline-offset-1"
    >
      <Icon icon={isDark ? Sun : Moon} size={16} />
    </button>
  );
}
