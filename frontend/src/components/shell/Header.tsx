import { ThemeToggle } from "@/components/ui/ThemeToggle";

export function Header() {
  return (
    <header className="h-12 border-b border-line bg-bg flex items-center justify-between px-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-[14px] tracking-[0.05em] text-ink">SHIFTWISE</span>
        <span className="font-mono text-[11px] text-ink-muted">
          v0.1.0 · {__BUILD_HASH__}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
      </div>
    </header>
  );
}
