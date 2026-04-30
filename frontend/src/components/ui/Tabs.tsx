import { useState } from "react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Tab = { id: string; label: string; content: ReactNode };

export function Tabs({ tabs, defaultId }: { tabs: Tab[]; defaultId?: string }) {
  const [active, setActive] = useState(defaultId ?? tabs[0]?.id);
  const current = tabs.find((t) => t.id === active);

  return (
    <div>
      <div className="flex border border-line-strong">
        {tabs.map((t) => {
          const on = t.id === active;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setActive(t.id)}
              className={cn(
                "h-10 px-4 border-r border-line-strong last:border-r-0",
                "font-sans text-[13px]",
                "transition-[background-color,color] duration-150",
                on
                  ? "bg-bg-elev text-ink font-semibold"
                  : "bg-transparent text-ink-muted hover:bg-bg-elev hover:text-ink",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="border border-t-0 border-line-strong p-4">{current?.content}</div>
    </div>
  );
}
