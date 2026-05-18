import { LiveIndicator } from "@/components/ui/LiveIndicator";

export function Footer({
  uptime = "12d 04:11:23",
  region = "Paris, FR",
  environment = "Production",
  version = "2.4.1",
}: {
  uptime?: string;
  region?: string;
  environment?: string;
  version?: string;
}) {
  const buildHash = (typeof __BUILD_HASH__ !== "undefined" ? __BUILD_HASH__ : "dev");

  const items: { label: string; value: string; tone?: "ok" | "muted" }[] = [
    { label: "Env", value: environment, tone: "ok" },
    { label: "Build", value: buildHash, tone: "muted" },
    { label: "Rev", value: `v${version}`, tone: "muted" },
    { label: "Region", value: region, tone: "muted" },
    { label: "Uptime", value: uptime, tone: "muted" },
  ];

  return (
    <footer className="px-2 flex items-center justify-between gap-4 flex-wrap pt-1">
      <LiveIndicator tone="ok" label="All systems operational" />
      <div className="flex items-center gap-5 overflow-x-auto">
        {items.map((it) => (
          <span
            key={it.label}
            className="flex items-center gap-1.5 text-[11px] tabular shrink-0"
          >
            <span className="text-[var(--text-muted)] font-medium">{it.label}</span>
            <span
              className="font-bold"
              style={{
                color:
                  it.tone === "ok"
                    ? "var(--alert-success-light)"
                    : "var(--text-primary)",
              }}
            >
              {it.value}
            </span>
          </span>
        ))}
      </div>
    </footer>
  );
}
