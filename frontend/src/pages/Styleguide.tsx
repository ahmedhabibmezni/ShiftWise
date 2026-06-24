import { useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Database,
  HardDrive,
  Plus,
  Rocket,
  ScanSearch,
  Server,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Checkbox } from "@/components/ui/Checkbox";
import { Badge } from "@/components/ui/Badge";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { Panel } from "@/components/ui/Panel";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { Tabs } from "@/components/ui/Tabs";
import { Icon } from "@/components/ui/Icon";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Gauge } from "@/components/ui/Gauge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Callout } from "@/components/ui/Callout";
import { Sparkline } from "@/components/ui/Sparkline";
import { StackedBar } from "@/components/ui/StackedBar";
import { PipelineStrip } from "@/components/PipelineStrip";

const TOKEN_GROUPS: { title: string; tokens: [string, string][] }[] = [
  {
    title: "Brand",
    tokens: [
      ["accent-primary", "var(--accent-primary)"],
      ["accent-light", "var(--accent-light)"],
      ["accent-deep", "var(--accent-deep)"],
    ],
  },
  {
    title: "Infrastructure",
    tokens: [
      ["blue-deep", "var(--blue-deep)"],
      ["blue-base", "var(--blue-base)"],
      ["blue-mid", "var(--blue-mid)"],
    ],
  },
  {
    title: "Alert",
    tokens: [
      ["alert-success", "var(--alert-success)"],
      ["alert-medium", "var(--alert-medium)"],
      ["alert-high", "var(--alert-high)"],
      ["alert-critical", "var(--alert-critical)"],
      ["alert-low", "var(--alert-low)"],
    ],
  },
  {
    title: "Substrate",
    tokens: [
      ["bg-app", "var(--bg-app)"],
      ["bg-app-mid", "var(--bg-app-mid)"],
      ["bg-app-deep", "var(--bg-app-deep)"],
    ],
  },
];

export default function Styleguide() {
  return (
    <div className="glass-budget-lite min-h-[100dvh] p-6 md:p-10">
      <header className="flex items-end justify-between gap-6 flex-wrap mb-8">
        <div>
          <div className="kicker mb-2">ShiftWise · Design System</div>
          <h1 className="text-[40px] font-bold tracking-[-0.025em] leading-[1.05] text-[var(--text-primary)]">
            Glass + Atmosphere
          </h1>
          <p className="mt-2 text-[14px] text-[var(--text-secondary)] max-w-[60ch]">
            Vision UI depth model with the OpenShift red-orange brand. All tokens, components,
            and patterns surface here.
          </p>
        </div>
        <ThemeToggle />
      </header>

      <Section title="Tokens">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {TOKEN_GROUPS.map((g) => (
            <Panel key={g.title} title={g.title}>
              <ul className="flex flex-col gap-2 mt-2">
                {g.tokens.map(([n, c]) => (
                  <li key={n} className="flex items-center gap-3">
                    <span
                      className="block w-9 h-9 rounded-xl shrink-0"
                      style={{ background: c, boxShadow: "var(--shadow-card)" }}
                    />
                    <div className="min-w-0">
                      <div className="text-[12px] font-bold text-[var(--text-primary)] truncate">
                        {n}
                      </div>
                      <div className="text-[10px] tabular text-[var(--text-muted)] truncate">
                        {c}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      </Section>

      <Section title="KPI Cards">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          <KPIPrimary label="VMs Discovered" value="12,847" delta="+8%" icon={ScanSearch} iconTone="accent" />
          <KPIPrimary label="Compatible" value="9,420" delta="+12%" icon={CheckCircle2} iconTone="blue" />
          <KPIPrimary label="Active" value="247" delta="+24%" icon={Rocket} iconTone="success" />
          <KPIPrimary label="Failed" value="18" delta="-32%" deltaTone="down" icon={Cpu} iconTone="warn" />
        </div>
      </Section>

      <Section title="Status Chips">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="ok">Compatible</Badge>
          <Badge variant="partial">Partial</Badge>
          <Badge variant="incompatible">Incompatible</Badge>
          <Badge variant="info">Info</Badge>
          <Badge variant="run">Running</Badge>
          <Badge variant="neutral">Neutral</Badge>
          <StatusBadge label="Migrating" tone="signal" />
          <StatusBadge label="Active" tone="ok" />
          <StatusBadge label="Failed" tone="err" />
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" leadingIcon={<Icon icon={Plus} size={14} />}>
            Primary
          </Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="primary" trailingIcon={<Icon icon={ArrowRight} size={14} />}>
            With trailing
          </Button>
          <IconButton variant="primary" aria-label="Add">
            <Plus size={16} strokeWidth={2.25} />
          </IconButton>
          <IconButton variant="secondary" aria-label="Server">
            <Server size={16} />
          </IconButton>
        </div>
      </Section>

      <Section title="Form Inputs">
        <Panel title="Form fields">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
            <Input placeholder="vSphere host…" />
            <Select>
              <option>vSphere</option>
              <option>KVM</option>
            </Select>
            <Textarea placeholder="Notes…" rows={3} className="md:col-span-2" />
            <label className="flex items-center gap-2.5 cursor-pointer">
              <Checkbox defaultChecked />
              <span className="text-[13px] text-[var(--text-primary)]">Verify SSL</span>
            </label>
          </div>
        </Panel>
      </Section>

      <Section title="Charts + Gauges">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Panel title="Readiness" hint="Hybrid scoring">
            <div className="flex justify-center mt-3">
              <Gauge value={87} label="Score" tone="ok" sublabel="Ready" />
            </div>
          </Panel>
          <Panel title="Throughput" hint="Last 24h">
            <Sparkline
              values={[12, 18, 22, 30, 28, 34, 41, 48, 52, 58, 60, 65, 71, 78]}
              width={360}
              height={80}
              className="mt-3"
            />
          </Panel>
          <Panel title="Distribution">
            <StackedBar
              segments={[
                { key: "ok",  label: "Compatible",   value: 92, color: "var(--alert-success)" },
                { key: "p",   label: "Partial",      value: 18, color: "var(--alert-high)" },
                { key: "ko",  label: "Incompatible", value: 6,  color: "var(--alert-critical)" },
              ]}
              height={12}
            />
          </Panel>
        </div>
      </Section>

      <Section title="Pipeline Strip">
        <Panel title="Migration Pipeline">
          <PipelineStrip
            stages={[
              { key: "discover", label: "Discovery", icon: ScanSearch, count: "12,847", meta: "100% scanned",     progress: 100, state: "done" },
              { key: "analyze",  label: "Analyzer",  icon: Cpu,        count: "9,420",  meta: "100% analysed",    progress: 100, state: "done" },
              { key: "convert",  label: "Converter", icon: HardDrive,  count: "3,847",  meta: "64% converted",    progress: 64,  state: "active" },
              { key: "adapt",    label: "Adapter",   icon: Database,   count: "1,204",  meta: "18% adapted",      progress: 18,  state: "pending" },
              { key: "migrate",  label: "Migrator",  icon: Rocket,     count: "512",    meta: "8% migrated",      progress: 8,   state: "pending" },
            ]}
          />
        </Panel>
      </Section>

      <Section title="Callouts">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Callout tone="ok" kicker="Healthy">All systems operational.</Callout>
          <Callout tone="info" kicker="Heads up">Auto-discovery is on.</Callout>
          <Callout tone="warn" kicker="Action needed">3 incompatibilities flagged.</Callout>
          <Callout tone="err" kicker="Failed">vm-legacy-win2008 conversion failed.</Callout>
        </div>
      </Section>

      <Section title="Tabs">
        <Tabs
          tabs={[
            {
              id: "details",
              label: "Details",
              content: <p className="text-[13px] text-[var(--text-secondary)]">Detail content goes here.</p>,
            },
            {
              id: "logs",
              label: "Logs",
              content: <p className="text-[13px] text-[var(--text-secondary)]">Stream of recent log lines.</p>,
            },
            {
              id: "events",
              label: "Events",
              content: <p className="text-[13px] text-[var(--text-secondary)]">Audit events.</p>,
            },
          ]}
        />
      </Section>

      <Section title="Progress + Live">
        <Panel title="Pipeline state">
          <div className="space-y-4">
            <ProgressBar value={62} variant="signal" showPct />
            <ProgressBar value={88} variant="ok" showPct />
            <ProgressBar value={34} variant="warn" showPct />
            <ProgressBar value={12} variant="err" showPct />
            <div className="flex items-center gap-4">
              <LiveIndicator label="Live" tone="ok" />
              <LiveIndicator label="Stalled" tone="warn" />
              <LiveIndicator label="Critical" tone="err" />
            </div>
          </div>
        </Panel>
      </Section>

      <Footer />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="mb-8">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="kicker mb-3 flex items-center gap-2 hover:text-[var(--text-primary)] transition-colors duration-150"
      >
        {title}
        <span aria-hidden>{open ? "—" : "+"}</span>
      </button>
      {open && children}
    </section>
  );
}

function Footer() {
  return (
    <div className="mt-12 pt-6 border-t border-[var(--hairline)] flex items-center justify-between text-[11px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
      <span>ShiftWise · Design System</span>
      <span>Vision UI depth model</span>
    </div>
  );
}
