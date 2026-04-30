import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Tab = {
  id: string;
  label: string;
  content: ReactNode;
};

type Props = {
  tabs: Tab[];
  defaultId?: string;
  className?: string;
};

export function Tabs({ tabs, defaultId, className }: Props) {
  const [active, setActive] = useState<string>(defaultId ?? tabs[0]?.id ?? "");
  const current = tabs.find((t) => t.id === active) ?? tabs[0];

  return (
    <div className={className}>
      <div role="tablist" className="flex border border-line">
        {tabs.map((t) => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActive(t.id)}
              className={cn(
                "h-8 px-3 font-mono text-[11px] uppercase tracking-[0.05em]",
                "border-r border-line last:border-r-0",
                "transition-[background-color,color]",
                isActive ? "bg-bg-elev text-ink" : "bg-bg text-ink-muted hover:text-ink",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="border border-t-0 border-line p-4">
        {current?.content}
      </div>
    </div>
  );
}
