import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { Select } from "@/components/ui/Select";
import { ThemeToggle } from "@/components/ui/ThemeToggle";

export function Header({
  title = "overview",
  timestamp = "14:22:01 UTC",
}: {
  title?: string;
  timestamp?: string;
}) {
  return (
    <header className="h-16 px-8 flex items-center justify-between border-b border-line bg-bg">
      <h1 className="text-h1 lowercase">{title}</h1>
      <div className="flex items-center gap-6">
        <LiveIndicator />
        <span className="font-mono text-[12px] tabular text-ink-muted">{timestamp}</span>
        <Select defaultValue="24h" className="h-10 w-32">
          <option value="1h">last 1h</option>
          <option value="24h">last 24h</option>
          <option value="7d">last 7d</option>
          <option value="30d">last 30d</option>
        </Select>
        <ThemeToggle />
      </div>
    </header>
  );
}
