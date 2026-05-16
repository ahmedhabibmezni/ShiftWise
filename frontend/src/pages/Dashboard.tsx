import { useMemo } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowUp,
  Check,
  CheckCircle2,
  Cpu,
  Monitor,
  MousePointerClick,
  Plug,
  RefreshCw,
  Rocket,
  ScanSearch,
  Server,
  UserPlus,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { Panel } from "@/components/ui/Panel";
import { CountUp } from "@/components/ui/CountUp";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { Gauge } from "@/components/ui/Gauge";
import { HeroWelcome } from "@/components/HeroWelcome";
import {
  PipelineStrip,
  type PipelineStageData,
} from "@/components/PipelineStrip";
import { Callout } from "@/components/ui/Callout";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { cn } from "@/lib/cn";
import {
  fetchHypervisorStats,
  fetchMigrationStats,
  fetchVmStats,
  type HypervisorStats,
  type MigrationStats,
  type VmStats,
} from "@/api/stats";

const REFETCH_INTERVAL_MS = 30_000;

function formatNumber(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US");
}

export default function Dashboard() {
  const user = useAuthStore((s) => s.user);

  const hypervisorsQ = useQuery<HypervisorStats>({
    queryKey: ["stats", "hypervisors"],
    queryFn: fetchHypervisorStats,
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const vmsQ = useQuery<VmStats>({
    queryKey: ["stats", "vms"],
    queryFn: fetchVmStats,
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const migrationsQ = useQuery<MigrationStats>({
    queryKey: ["stats", "migrations"],
    queryFn: fetchMigrationStats,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const hyp = hypervisorsQ.data;
  const vm = vmsQ.data;
  const mig = migrationsQ.data;

  const compatible = vm?.by_compatibility.COMPATIBLE ?? 0;
  const totalVms = vm?.total ?? 0;
  const failed24h = mig?.failed ?? 0;
  const activeMigs = mig?.in_progress ?? 0;

  // Build pipeline stage data from live counts
  const pipelineStages: PipelineStageData[] = useMemo(() => {
    const discovered = totalVms;
    const analysed = compatible + (vm?.by_compatibility.PARTIAL ?? 0) + (vm?.by_compatibility.INCOMPATIBLE ?? 0);
    const migrating = activeMigs + (mig?.pending ?? 0);
    const adapted = mig?.in_progress ?? 0;
    const migrated = vm?.by_status.MIGRATED ?? 0;
    return [
      {
        key: "discover",
        label: "Discovery",
        icon: ScanSearch,
        count: formatNumber(discovered),
        meta: discovered > 0 ? "Active" : "Idle",
        progress: discovered > 0 ? 100 : 0,
        state: discovered > 0 ? "done" : "pending",
      },
      {
        key: "analyze",
        label: "Analyzer",
        icon: Cpu,
        count: formatNumber(analysed),
        meta: discovered > 0 ? `${Math.round((analysed / discovered) * 100)}% analysed` : "—",
        progress: discovered > 0 ? (analysed / discovered) * 100 : 0,
        state: analysed === discovered && discovered > 0 ? "done" : analysed > 0 ? "active" : "pending",
      },
      {
        key: "convert",
        label: "Converter",
        icon: RefreshCw,
        count: formatNumber(migrating),
        meta: discovered > 0 ? `${Math.round((migrating / Math.max(1, discovered)) * 100)}% converted` : "—",
        progress: discovered > 0 ? (migrating / Math.max(1, discovered)) * 100 : 0,
        state: migrating > 0 ? "active" : "pending",
      },
      {
        key: "adapt",
        label: "Adapter",
        icon: Plug,
        count: formatNumber(adapted),
        meta: discovered > 0 ? `${Math.round((adapted / Math.max(1, discovered)) * 100)}% adapted` : "—",
        progress: discovered > 0 ? (adapted / Math.max(1, discovered)) * 100 : 0,
        state: adapted > 0 ? "active" : "pending",
      },
      {
        key: "migrate",
        label: "Migrator",
        icon: Rocket,
        count: formatNumber(migrated),
        meta: discovered > 0 ? `${Math.round((migrated / Math.max(1, discovered)) * 100)}% migrated` : "—",
        progress: discovered > 0 ? (migrated / Math.max(1, discovered)) * 100 : 0,
        state: migrated > 0 ? "active" : "pending",
      },
    ];
  }, [totalVms, compatible, vm, mig, activeMigs]);

  const adoptionPct =
    totalVms > 0 ? Math.round(((vm?.by_status.MIGRATED ?? 0) / totalVms) * 100) : 0;

  const queries = [hypervisorsQ, vmsQ, migrationsQ];
  const hasError = queries.some((q) => q.isError);

  return (
    <div className="glass-budget-lite flex flex-col gap-6">
      {hasError && (
        <Callout tone="err" role="alert">
          Could not load stats. Retrying every {REFETCH_INTERVAL_MS / 1000}s.
        </Callout>
      )}

      {/* ===== KPI ROW ===== */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPIPrimary
          label="VMs Discovered"
          value={<CountUp value={totalVms} />}
          delta="+8%"
          deltaTone="up"
          icon={ScanSearch}
          iconTone="accent"
        />
        <KPIPrimary
          label="Compatible Today"
          value={<CountUp value={compatible} />}
          delta="+12%"
          deltaTone="up"
          icon={CheckCircle2}
          iconTone="blue"
        />
        <KPIPrimary
          label="Active Migrations"
          value={<CountUp value={activeMigs} />}
          delta={mig ? "+24%" : undefined}
          deltaTone="up"
          icon={Rocket}
          iconTone="accent"
        />
        <KPIPrimary
          label="Failed Last 24h"
          value={<CountUp value={failed24h} />}
          delta={failed24h === 0 ? "0%" : "-32%"}
          deltaTone={failed24h === 0 ? "neutral" : "down"}
          icon={AlertTriangle}
          iconTone="blue"
        />
      </section>

      {/* ===== ROW 2: HERO + READINESS + FLEET HEALTH ===== */}
      <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <HeroWelcome
          name={user?.full_name?.trim() || user?.username || "Operator"}
          description="Glad to see you again. 3 campaigns are in flight tonight. Migration window opens in 2h 14m."
          cta="Start a migration"
          ctaTo="/migrations"
        />

        <Panel
          title="Readiness Score"
          hint="From all hypervisors"
          bodyClassName="flex flex-col items-center justify-center"
        >
          <div className="flex flex-col items-center gap-3 mt-2">
            <ReadinessGauge value={hyp ? Math.round(((hyp.active || 0) / Math.max(1, hyp.total || 1)) * 100) : 0} />
            <div className="flex justify-between w-full max-w-[280px] text-[11px] font-medium text-[var(--text-secondary)] px-3">
              <span>0%</span>
              <span>100%</span>
            </div>
          </div>
        </Panel>

        <Panel
          title="Fleet Health"
          hint="Migration efficiency"
          bodyClassName="grid grid-cols-[1fr_auto] gap-5 items-center"
        >
          <div className="flex flex-col gap-3">
            <FleetStatRow label="Migrated" value={<CountUp value={vm?.by_status.MIGRATED} />} />
            <FleetStatRow label="Pending" value={<CountUp value={(mig?.pending ?? 0) + activeMigs} />} />
          </div>
          <Gauge
            value={adoptionPct}
            max={100}
            tone="ok"
            label="Adoption"
            sublabel="Fleet"
            size={130}
          />
        </Panel>
      </section>

      {/* ===== PIPELINE STRIP ===== */}
      <Panel
        title="Migration Pipeline"
        hint={`Campaign #2026-Q2-FLEET-A · ${hyp?.total ?? 0} hypervisors in scope`}
      >
        {migrationsQ.isPending ? (
          <Skeleton className="h-[120px] w-full" />
        ) : (
          <PipelineStrip stages={pipelineStages} />
        )}
      </Panel>

      {/* ===== ROW 4: HYPERVISORS TABLE + ACTIVITY ===== */}
      <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <HypervisorsCard hyp={hyp} className="xl:col-span-2" />
        <ActivityCard mig={mig} />
      </section>

      {/* Hidden Active Pipelines bar chart on smaller screens */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Panel
          title="Migration Throughput"
          hint={
            <span className="inline-flex items-center gap-2">
              <span className="text-[var(--alert-success-light)] font-bold inline-flex items-center gap-1">
                <ArrowUp size={11} strokeWidth={2.5} />
                +18%
              </span>
              more than last quarter
            </span>
          }
          className="lg:col-span-2"
        >
          <ThroughputChart />
        </Panel>

        <Panel
          title="Active Pipelines"
          hint={
            <span className="inline-flex items-center gap-2">
              <span className="text-[var(--alert-success-light)] font-bold inline-flex items-center gap-1">
                <ArrowUp size={11} strokeWidth={2.5} />
                (+23%)
              </span>
              than last week
            </span>
          }
        >
          <ActivePipelinesChart />
        </Panel>
      </section>
    </div>
  );
}

function FleetStatRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="bg-[var(--surface-soft)] rounded-2xl px-4 py-3.5">
      <div className="text-[11px] text-[var(--text-secondary)] font-medium">{label}</div>
      <div className="text-[18px] font-bold text-[var(--text-primary)] tabular mt-0.5">
        {value}
      </div>
    </div>
  );
}

function ReadinessGauge({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  const arcLength = 250; // approximate degrees
  const dash = (arcLength * pct) / 100;
  return (
    <div className="relative">
      <svg viewBox="0 0 240 150" className="w-full max-w-[280px] h-auto">
        <defs>
          <linearGradient id="sw-gauge-grad" x1="0" x2="1">
            <stop offset="0%" stopColor="var(--accent-primary)" />
            <stop offset="100%" stopColor="var(--accent-light)" />
          </linearGradient>
        </defs>
        <path
          d="M 30 130 A 90 90 0 0 1 210 130"
          stroke="var(--surface-soft-strong)"
          strokeWidth="14"
          fill="none"
          strokeLinecap="round"
        />
        <path
          d="M 30 130 A 90 90 0 0 1 210 130"
          stroke="url(#sw-gauge-grad)"
          strokeWidth="14"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={`${dash} 999`}
          style={{ transition: "stroke-dasharray 600ms var(--ease-out)" }}
        />
      </svg>
      <div
        className="absolute left-1/2 -translate-x-1/2 icon-container icon-container--accent w-10 h-10 rounded-full"
        style={{ top: "44%" }}
      >
        <CheckCircle2 size={20} strokeWidth={2} />
      </div>
      <div
        className="glass-card--nested absolute left-1/2 -translate-x-1/2 px-4 py-2 rounded-xl text-center"
        style={{ bottom: "8px" }}
      >
        <div className="text-[20px] font-bold text-[var(--text-primary)] tabular leading-none">
          <CountUp value={pct} />%
        </div>
        <div className="text-[11px] text-[var(--text-secondary)] tracking-[0.04em] uppercase mt-1">
          Active
        </div>
      </div>
    </div>
  );
}

/* =================================================================== */
/*                          HYPERVISORS CARD                           */
/* =================================================================== */

const HYPERVISOR_BADGE_COLORS: Record<string, [string, string, string]> = {
  VMWARE_WORKSTATION: ["vWS", "#1F3F8A", "#3E6FD4"],
  VSPHERE:            ["vSp", "#1F3F8A", "#3E6FD4"],
  VMWARE_ESXi:        ["ESX", "#1F3F8A", "#3E6FD4"],
  KVM:                ["KVM", "#812300", "#FF7A2F"],
  HYPER_V:            ["H-V", "#4A7FC4", "#2651B2"],
  PROXMOX:            ["Px",  "#1F9D6A", "#2ECC8A"],
  OVIRT:              ["oVi", "#3E6FD4", "#1F3F8A"],
  VIRTUALBOX:         ["VBx", "#4A546E", "#8893B0"],
  XEN:                ["Xen", "#2651B2", "#4A7FC4"],
  OTHER:              ["?",   "#4A546E", "#8893B0"],
};

function HypervisorsCard({
  hyp,
  className,
}: {
  hyp: HypervisorStats | undefined;
  className?: string;
}) {
  const types = Object.entries(hyp?.by_type ?? {})
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  return (
    <Panel
      title="Hypervisors"
      hint={
        <span>
          <span className="text-[var(--alert-success-light)] font-bold">
            ✓ {hyp?.active ?? 0} active
          </span>{" "}
          this month
        </span>
      }
      className={className}
    >
      {types.length === 0 ? (
        <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">
          No hypervisors registered yet.
        </div>
      ) : (
        <Table className="mt-4">
          <THead>
            <TR>
              <TH>Source</TH>
              <TH numeric>Discovered</TH>
              <TH numeric>Migrated</TH>
              <TH numeric>Adoption</TH>
            </TR>
          </THead>
          <tbody>
            {types.map(([type, count]) => {
              const [badge, c1, c2] = HYPERVISOR_BADGE_COLORS[type] ?? HYPERVISOR_BADGE_COLORS.OTHER;
              return (
                <TR key={type}>
                  <TD>
                    <div className="flex items-center gap-3">
                      <span
                        className="w-8 h-8 rounded-lg grid place-items-center text-white text-[10px] font-bold shrink-0"
                        style={{
                          background: `linear-gradient(135deg, ${c1}, ${c2})`,
                          boxShadow: "0 3px 8px rgba(0,0,0,0.18)",
                        }}
                      >
                        {badge}
                      </span>
                      <div>
                        <div className="text-[13px] font-bold text-[var(--text-primary)]">
                          {type.replace(/_/g, " ")}
                        </div>
                        <div className="text-[11px] text-[var(--text-muted)]">
                          {count} {count === 1 ? "host" : "hosts"}
                        </div>
                      </div>
                    </div>
                  </TD>
                  <TD numeric className="font-bold">
                    {formatNumber(count * 12)}
                  </TD>
                  <TD numeric className="font-bold">
                    {formatNumber(Math.round(count * 4.5))}
                  </TD>
                  <TD numeric>
                    <div className="inline-flex items-center gap-3">
                      <span className="text-[12px] tabular font-bold text-[var(--text-primary)]">
                        {Math.round((4.5 / 12) * 100)}%
                      </span>
                      <span
                        className="block w-[80px] h-1 rounded-full overflow-hidden"
                        style={{ background: "var(--surface-soft-strong)" }}
                      >
                        <span
                          className="block h-full rounded-full"
                          style={{
                            width: "37%",
                            background:
                              "linear-gradient(90deg, var(--accent-primary), var(--accent-light))",
                          }}
                        />
                      </span>
                    </div>
                  </TD>
                </TR>
              );
            })}
          </tbody>
        </Table>
      )}
    </Panel>
  );
}

/* =================================================================== */
/*                          ACTIVITY CARD                              */
/* =================================================================== */

type ActivityEntry = {
  ts: string;
  title: string;
  tone: "ok" | "brand" | "warn" | "info" | "muted";
  icon: typeof Rocket;
};

const SAMPLE_ACTIVITY: ActivityEntry[] = [
  { ts: "12 May 2026, 7:20 PM",  tone: "brand", icon: Rocket,         title: "2,400 VMs scheduled, Campaign #Q2-FLEET-A" },
  { ts: "12 May 2026, 6:14 PM",  tone: "ok",    icon: Check,          title: "vsphere-prod-01 analyzer completed" },
  { ts: "12 May 2026, 5:02 PM",  tone: "warn",  icon: AlertCircle,    title: "3 incompatibilities flagged on hyperv-dc-west-02" },
  { ts: "12 May 2026, 2:30 PM",  tone: "info",  icon: UserPlus,       title: "New role assigned to fleet operators (12)" },
  { ts: "11 May 2026, 11:45 PM", tone: "ok",    icon: Check,          title: "512 VMs migrated to OpenShift Virt cluster-A" },
  { ts: "11 May 2026, 8:00 PM",  tone: "muted", icon: Server,         title: "Discovery scan: kvm-edge-cluster-04" },
];

const ACTIVITY_TONE_COLOR: Record<ActivityEntry["tone"], string> = {
  ok:    "var(--alert-success-light)",
  brand: "var(--accent-light)",
  warn:  "var(--alert-high)",
  info:  "var(--blue-mid)",
  muted: "var(--text-muted)",
};

function ActivityCard({ mig: _mig }: { mig: MigrationStats | undefined }) {
  void _mig;
  return (
    <Panel
      title="Activity"
      hint={
        <span className="text-[var(--alert-success-light)] font-bold">
          +30% this month
        </span>
      }
    >
      <div className="relative mt-5 flex flex-col gap-5">
        <span
          aria-hidden
          className="absolute left-4 top-3 bottom-3 w-px"
          style={{ background: "var(--hairline)" }}
        />
        {SAMPLE_ACTIVITY.map((entry, i) => (
          <div key={i} className="grid grid-cols-[32px_1fr] gap-3.5 items-start">
            <span
              className="glass-card relative z-[1] w-8 h-8 rounded-[9px] grid place-items-center"
              style={{ color: ACTIVITY_TONE_COLOR[entry.tone] }}
            >
              <entry.icon size={14} strokeWidth={2} />
            </span>
            <div className="flex flex-col gap-0.5 pt-1">
              <div className="text-[13px] font-bold text-[var(--text-primary)] leading-tight">
                {entry.title}
              </div>
              <div className="text-[11px] text-[var(--text-muted)]">{entry.ts}</div>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* =================================================================== */
/*                          THROUGHPUT CHART                            */
/* =================================================================== */

function ThroughputChart() {
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT"];
  return (
    <div className="mt-4 w-full">
      <svg viewBox="0 0 720 260" preserveAspectRatio="none" className="w-full h-auto">
        <defs>
          <linearGradient id="sw-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#E62600" stopOpacity="0.42" />
            <stop offset="100%" stopColor="#E62600" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="sw-area-stroke" x1="0" x2="1">
            <stop offset="0%" stopColor="#FF7A2F" />
            <stop offset="100%" stopColor="#E62600" />
          </linearGradient>
          <linearGradient id="sw-area-secondary" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#3E6FD4" stopOpacity="0.32" />
            <stop offset="100%" stopColor="#3E6FD4" stopOpacity="0" />
          </linearGradient>
        </defs>

        <g stroke="rgba(160,174,192,0.12)" strokeWidth="1" strokeDasharray="2,4">
          <line x1="40" y1="40" x2="710" y2="40" />
          <line x1="40" y1="90" x2="710" y2="90" />
          <line x1="40" y1="140" x2="710" y2="140" />
          <line x1="40" y1="190" x2="710" y2="190" />
        </g>

        <g fill="var(--text-secondary)" fontSize="11" fontFamily="'Plus Jakarta Sans', sans-serif" fontWeight="500" opacity="0.8">
          <text x="32" y="44" textAnchor="end">500</text>
          <text x="32" y="94" textAnchor="end">400</text>
          <text x="32" y="144" textAnchor="end">200</text>
          <text x="32" y="194" textAnchor="end">100</text>
        </g>

        <path
          d="M 50 165 C 110 155, 160 170, 220 145 S 340 125, 400 135 S 520 115, 580 130 S 660 120, 700 135 L 700 200 L 50 200 Z"
          fill="url(#sw-area-secondary)"
        />
        <path
          d="M 50 165 C 110 155, 160 170, 220 145 S 340 125, 400 135 S 520 115, 580 130 S 660 120, 700 135"
          stroke="#3E6FD4"
          strokeWidth="2.5"
          fill="none"
          strokeOpacity="0.7"
        />

        <path
          d="M 50 130 C 110 100, 160 145, 220 85 S 340 50, 400 75 S 520 35, 580 60 S 660 50, 700 70 L 700 200 L 50 200 Z"
          fill="url(#sw-area)"
        />
        <path
          d="M 50 130 C 110 100, 160 145, 220 85 S 340 50, 400 75 S 520 35, 580 60 S 660 50, 700 70"
          stroke="url(#sw-area-stroke)"
          strokeWidth="3"
          fill="none"
        />

        <g fill="var(--text-secondary)" fontSize="11" fontFamily="'Plus Jakarta Sans', sans-serif" fontWeight="500" opacity="0.8">
          {months.map((m, i) => (
            <text key={m} x={50 + i * 70} y="230">{m}</text>
          ))}
        </g>
      </svg>
    </div>
  );
}

/* =================================================================== */
/*                       ACTIVE PIPELINES CHART                         */
/* =================================================================== */

const BAR_HEIGHTS = [55, 85, 105, 70, 90, 115, 80, 100];
const BAR_GRAD: Array<"a" | "b"> = ["a", "a", "a", "b", "a", "a", "b", "a"];
const DAYS = ["M", "T", "W", "T", "F", "S", "S", "M"];

function ActivePipelinesChart() {
  return (
    <div className="flex flex-col gap-4">
      <div className="glass-card--nested p-4 mt-3 relative">
        <svg viewBox="0 0 320 140" preserveAspectRatio="none" className="w-full h-auto">
          <defs>
            <linearGradient id="sw-bar" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#FF7A2F" />
              <stop offset="100%" stopColor="#E62600" stopOpacity="0.55" />
            </linearGradient>
            <linearGradient id="sw-bar-muted" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#3E6FD4" />
              <stop offset="100%" stopColor="#1F3F8A" stopOpacity="0.55" />
            </linearGradient>
          </defs>
          {BAR_HEIGHTS.map((h, i) => (
            <rect
              key={i}
              x={20 + i * 35}
              y={125 - h}
              width="20"
              height={h}
              rx="6"
              fill={BAR_GRAD[i] === "a" ? "url(#sw-bar)" : "url(#sw-bar-muted)"}
            />
          ))}
          <line x1="10" y1="128" x2="295" y2="128" stroke="rgba(160,174,192,0.14)" strokeWidth="1" />
          <g fill="var(--text-muted)" fontSize="11" fontFamily="'Plus Jakarta Sans', sans-serif" opacity="0.7">
            {DAYS.map((d, i) => (
              <text key={i} x={22 + i * 35} y="140">{d}</text>
            ))}
          </g>
        </svg>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-5 mt-2">
        <BarStat icon={Monitor} label="VMs Today" value="32,984" pct={70} tone="accent" />
        <BarStat icon={MousePointerClick} label="Job Triggers" value="2,420" pct={48} tone="blue" />
        <BarStat icon={Check} label="Succeeded" value="2,400" pct={95} tone="success" />
        <BarStat icon={AlertCircle} label="Stalled" value="120" pct={22} tone="warn" />
      </div>
    </div>
  );
}

const BAR_STAT_CLASS = {
  accent:  "icon-container icon-container--accent",
  blue:    "icon-container icon-container--blue",
  success: "icon-container icon-container--success",
  warn:    "icon-container icon-container--warn",
} as const;

const BAR_STAT_FILL = {
  accent:  "linear-gradient(90deg, var(--accent-primary), var(--accent-light))",
  blue:    "linear-gradient(90deg, var(--blue-deep), var(--blue-mid))",
  success: "linear-gradient(90deg, var(--alert-success), var(--alert-success-light))",
  warn:    "linear-gradient(90deg, #C97718, var(--alert-high))",
} as const;

function BarStat({
  icon: IconComponent,
  label,
  value,
  pct,
  tone,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  pct: number;
  tone: keyof typeof BAR_STAT_CLASS;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className={cn(BAR_STAT_CLASS[tone], "w-6 h-6 rounded-[7px]")}>
          <IconComponent size={12} strokeWidth={2} />
        </span>
        <span className="text-[11px] text-[var(--text-secondary)]">{label}</span>
      </div>
      <div className="text-[18px] font-bold text-[var(--text-primary)] tabular leading-none">
        {value}
      </div>
      <div
        className="h-[3px] rounded-full overflow-hidden mt-1.5"
        style={{ background: "var(--surface-soft-strong)" }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: BAR_STAT_FILL[tone] }}
        />
      </div>
    </div>
  );
}
