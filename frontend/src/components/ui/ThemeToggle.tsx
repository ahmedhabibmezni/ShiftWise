import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/cn";

/**
 * Sun/moon glass-card pill. The icons crossfade + rotate based on the
 * active theme (cf. dashboard-target.html). Default size 36×36; pass a
 * className to override.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className={cn(
        "glass-card relative inline-flex items-center justify-center",
        "h-9 w-9 rounded-xl text-accent-light",
        "transition-colors duration-200 hover:text-accent-primary",
        "overflow-hidden",
        className,
      )}
    >
      <Sun
        size={16}
        strokeWidth={2}
        className={cn(
          "absolute transition-all duration-[var(--dur-slow)]",
          theme === "dark"
            ? "opacity-0 -rotate-90 scale-50"
            : "opacity-100 rotate-0 scale-100",
        )}
      />
      <Moon
        size={16}
        strokeWidth={2}
        className={cn(
          "absolute transition-all duration-[var(--dur-slow)]",
          theme === "dark"
            ? "opacity-100 rotate-0 scale-100"
            : "opacity-0 rotate-90 scale-50",
        )}
      />
    </button>
  );
}
