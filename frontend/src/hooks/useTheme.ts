import { useEffect, useState, useCallback } from "react";
import {
  applyTheme,
  getCurrentTheme,
  toggleTheme as applyToggle,
  type Theme,
} from "@/lib/theme";

export function useTheme(): {
  theme: Theme;
  setTheme: (next: Theme) => void;
  toggle: () => void;
  toggleTheme: () => void;
} {
  const [theme, setThemeState] = useState<Theme>(() => getCurrentTheme());

  useEffect(() => {
    const observer = new MutationObserver(() => setThemeState(getCurrentTheme()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  const setTheme = useCallback((next: Theme) => {
    applyTheme(next);
  }, []);

  const toggle = useCallback(() => {
    applyToggle();
  }, []);

  return { theme, setTheme, toggle, toggleTheme: toggle };
}
