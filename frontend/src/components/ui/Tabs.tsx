import { useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Tab = { id: string; label: string; content: ReactNode };

/** Horizontal inset of the underline from each edge of the active tab. */
const INDICATOR_INSET = 8;

/**
 * Tabbed panel — a glass card with pill-style tabs along the top.
 *
 * Conformant to the WAI-ARIA tabs pattern: roving `tabIndex` (only the active
 * tab is in the tab order), Arrow/Home/End move and activate, and each panel
 * carries `role="tabpanel"` linked back to its tab via `aria-labelledby`.
 *
 * The active underline is a single element that slides between tabs, measured
 * from the active button — not a marker re-rendered inside each tab, which
 * would teleport. `transform` + `width` stay on this leaf span, so no glass
 * card ever gets a transformed ancestor.
 */
export function Tabs({ tabs, defaultId }: { tabs: Tab[]; defaultId?: string }) {
  const [active, setActive] = useState(defaultId ?? tabs[0]?.id);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });
  const activeIndex = Math.max(
    0,
    tabs.findIndex((t) => t.id === active),
  );

  // Track the active tab's box so the underline can slide to it. ResizeObserver
  // keeps it aligned through responsive reflow and late web-font metrics.
  useLayoutEffect(() => {
    const measure = () => {
      const btn = tabRefs.current[activeIndex];
      if (!btn) return;
      setIndicator({
        left: btn.offsetLeft + INDICATOR_INSET,
        width: Math.max(0, btn.offsetWidth - INDICATOR_INSET * 2),
      });
    };
    measure();
    // ResizeObserver is unavailable in some test/SSR environments; the
    // one-shot measure above still positions the underline correctly there.
    if (typeof ResizeObserver === "undefined" || !listRef.current) return;
    const ro = new ResizeObserver(measure);
    ro.observe(listRef.current);
    return () => ro.disconnect();
  }, [activeIndex, tabs.length]);

  const focusTab = (index: number) => {
    const next = (index + tabs.length) % tabs.length;
    setActive(tabs[next].id);
    tabRefs.current[next]?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    switch (e.key) {
      case "ArrowRight":
        focusTab(activeIndex + 1);
        break;
      case "ArrowLeft":
        focusTab(activeIndex - 1);
        break;
      case "Home":
        focusTab(0);
        break;
      case "End":
        focusTab(tabs.length - 1);
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  return (
    <div className="glass-card overflow-hidden">
      <div
        ref={listRef}
        role="tablist"
        onKeyDown={onKeyDown}
        className="relative z-[1] flex items-center gap-1 px-4 pt-3 border-b border-[var(--hairline)]"
      >
        {tabs.map((t, i) => {
          const on = t.id === active;
          return (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`sw-tab-${t.id}`}
              aria-selected={on}
              aria-controls={`sw-tabpanel-${t.id}`}
              tabIndex={on ? 0 : -1}
              onClick={() => setActive(t.id)}
              className={cn(
                "relative h-10 px-4 text-[13px] font-semibold rounded-t-[10px]",
                "transition-colors duration-200",
                on
                  ? "text-[var(--text-primary)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              )}
            >
              {t.label}
            </button>
          );
        })}
        <span
          aria-hidden
          className="absolute left-0 h-[2px] rounded-full"
          style={{
            bottom: -1,
            width: indicator.width,
            transform: `translateX(${indicator.left}px)`,
            transition:
              "transform var(--dur-slow) var(--ease-out-quint), width var(--dur-slow) var(--ease-out-quint)",
            background:
              "linear-gradient(90deg, var(--accent-primary), var(--accent-light))",
          }}
        />
      </div>
      {tabs.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          id={`sw-tabpanel-${t.id}`}
          aria-labelledby={`sw-tab-${t.id}`}
          tabIndex={0}
          hidden={t.id !== active}
          className="relative z-[1] p-6"
        >
          {t.content}
        </div>
      ))}
    </div>
  );
}
