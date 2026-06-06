import { LiveIndicator } from "@/components/ui/LiveIndicator";

export function Footer() {
  // Real values only: the deploy environment is derived from the Vite build
  // mode, and the build hash is injected at build time. The previously
  // fabricated Rev / Region / Uptime fields were removed.
  const environment = import.meta.env.PROD ? "Production" : "Development";
  const buildHash = (typeof __BUILD_HASH__ !== "undefined" ? __BUILD_HASH__ : "dev");

  const items: { label: string; value: string; tone?: "ok" | "muted" }[] = [
    { label: "Env", value: environment, tone: "ok" },
    { label: "Build", value: buildHash, tone: "muted" },
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
