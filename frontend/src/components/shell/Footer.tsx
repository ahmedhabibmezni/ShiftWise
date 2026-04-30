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
    { label: "uptime", value: uptime },
    { label: "région", value: region },
    { label: "environnement", value: environment, signal: true },
    { label: "version", value: version },
    { label: "build", value: buildHash },
  ];

  return (
    <footer className="h-12 px-8 flex items-center gap-8 border-t border-line bg-bg">
      {items.map((it) => (
        <span key={it.label} className="flex items-center gap-2 font-mono text-[11px] uppercase tabular">
          <span className="text-ink-muted">{it.label}</span>
          <span
            className={it.signal ? "text-signal" : "text-ink"}
            style={{ letterSpacing: "0.02em" }}
          >
            {it.value}
          </span>
        </span>
      ))}
    </footer>
  );
}
