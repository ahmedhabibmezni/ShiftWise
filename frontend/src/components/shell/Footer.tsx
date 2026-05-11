export function Footer({
  uptime = "12d 04:11:23",
  region = "paris, fr",
  environment = "production",
  version = "2.4.1",
}: {
  uptime?: string;
  region?: string;
  environment?: string;
  version?: string;
}) {
  const buildHash = (typeof __BUILD_HASH__ !== "undefined" ? __BUILD_HASH__ : "dev") as string;

  const items: { label: string; value: string; signal?: boolean }[] = [
    { label: "env", value: environment, signal: true },
    { label: "build", value: buildHash },
    { label: "rev", value: `v${version}` },
    { label: "region", value: region },
    { label: "uptime", value: uptime },
  ];

  return (
    <footer className="h-9 px-6 flex items-center justify-between border-t border-line bg-bg-elev">
      <div className="flex items-center gap-1.5">
        <span
          aria-hidden
          className="block h-1 w-1 bg-ok rounded-full"
          style={{ animation: "shiftwise-pulse 2.4s var(--ease-out) infinite" }}
        />
        <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted">
          all systems operational
        </span>
      </div>
      <div className="flex items-center gap-5 overflow-x-auto">
        {items.map((it) => (
          <span
            key={it.label}
            className="flex items-center gap-1.5 font-mono text-[10px] uppercase tabular shrink-0"
          >
            <span className="text-ink-faint">{it.label}</span>
            <span className={it.signal ? "text-signal" : "text-ink"}>
              {it.value}
            </span>
          </span>
        ))}
      </div>
    </footer>
  );
}
