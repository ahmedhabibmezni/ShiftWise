import { useEffect, useState, useCallback } from "react";
import { getCurrentTheme, toggleTheme as applyToggle, type Theme } from "@/lib/theme";

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(() => getCurrentTheme());

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(getCurrentTheme()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  const toggle = useCallback(() => {
    applyToggle();
  }, []);

  return { theme, toggle };
}
