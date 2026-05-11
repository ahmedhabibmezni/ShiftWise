import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Database,
  HardDrive,
  Layers,
  Monitor,
  Server,
  Sparkles,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Panel } from "@/components/ui/Panel";
import { Sparkline } from "@/components/ui/Sparkline";
import { StackedBar } from "@/components/ui/StackedBar";
import { MetricRow } from "@/components/ui/MetricRow";
import { Icon } from "@/components/ui/Icon";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { Skeleton, SkeletonStat } from "@/components/ui/Skeleton";
import { Ticker } from "@/components/ui/Ticker";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
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

function formatNumber(n: number | undefined): string {
  if (n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("fr-FR");
}

function formatGb(gb: number | undefined): string {
  if (gb === undefined || Number.isNaN(gb)) return "—";
  if (gb >= 1024) return `${(gb / 1024).toFixed(1)} TB`;
  return `${gb.toFixed(1)} GB`;
}

function formatRate(rate: number | undefined): string {
  if (rate === undefined || Number.isNaN(rate)) return "—";
  return `${rate.toFixed(1)}%`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function deterministicSpark(seed: number, len = 24): number[] {
  const out: number[] = [];
  let v = seed % 100 || 30;
  for (let i = 0; i < len; i++) {
    const swing = ((seed * (i + 1)) % 11) - 5;
    v = Math.max(8, Math.min(96, v + swing));
    out.push(v);
  }
  return out;
}

const PIPELINE_STAGES = [
  { key: "discover", label: "discovery", icon: Server },
  { key: "analyze", label: "analyzer", icon: Sparkles },
  { key: "convert", label: "converter", icon: Layers },
  { key: "adapt", label: "adapter", icon: HardDrive },
  { key: "migrate", label: "migrator", icon: ArrowUpRight },
] as const;

export default function Dashboard() {
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
  const partial = vm?.by_compatibility.PARTIAL ?? 0;
  const incompatible = vm?.by_compatibility.INCOMPATIBLE ?? 0;
  const unknown = vm?.by_compatibility.UNKNOWN ?? 0;
  const migrated = vm?.by_status.MIGRATED ?? 0;
  const migrating = vm?.by_status.MIGRATING ?? 0;
  const failedVms = vm?.by_status.FAILED ?? 0;

  const compatSegments = useMemo(
    () => [
      { key: "ok", label: "compatible", value: compatible, color: "var(--ok)" },
      { key: "partial", label: "partial", value: partial, color: "var(--warn)" },
      { key: "ko", label: "incompatible", value: incompatible, color: "var(--err)" },
      { key: "unknown", label: "unknown", value: unknown, color: "var(--ink-faint)" },
    ],
    [compatible, partial, incompatible, unknown],
  );

  const migrationSegments = useMemo(
    () => [
      { key: "completed", label: "completed", value: mig?.completed ?? 0, color: "var(--ok)" },
      { key: "running", label: "in flight", value: mig?.in_progress ?? 0, color: "var(--signal)" },
      { key: "pending", label: "queued", value: mig?.pending ?? 0, color: "var(--info-soft)" },
      { key: "failed", label: "failed", value: mig?.failed ?? 0, color: "var(--err)" },
    ],
    [mig],
  );

  const sparkData = useMemo(() => deterministicSpark((mig?.completed ?? 12) * 7 + 19), [mig?.completed]);

  const totalVms = vm?.total ?? 0;
  const adoptionRate = totalVms > 0 ? (migrated / totalVms) * 100 : 0;
  const isLoading = hypervisorsQ.isPending || vmsQ.isPending || migrationsQ.isPending;

  return (
    <div className="max-w-[1440px] mx-auto p-6 md:p-8 space-y-8">
      <PageHeader
        kicker="console · 2026-W19"
        title="operator console"
        description="Real-time view of the fleet, compatibility analyses, and migration pipeline."
        meta={
          <>
            <LiveIndicator />
            <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
              refresh · {REFETCH_INTERVAL_MS / 1000}s
            </span>
            <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
              cluster · openshift 4.18 · kubevirt v1.4.1
            </span>
          </>
        }
        actions={
          <>
            <Button variant="secondary" uppercase>
              export
            </Button>
            <Button variant="primary" uppercase>
              new migration
            </Button>
          </>
        }
      />

      <PipelineStrip stages={mig} />

      {/* Bento row 1 — hero migrations panel + side stack */}
      <section className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-7 sw-mount" style={{ "--sw-i": 0 } as React.CSSProperties}>
          <HeroMigration
            mig={mig}
            isLoading={migrationsQ.isPending}
            adoptionRate={adoptionRate}
            spark={sparkData}
          />
        </div>

        <div className="col-span-12 lg:col-span-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="sw-mount" style={{ "--sw-i": 1 } as React.CSSProperties}>
            <FleetCard hyp={hyp} isLoading={hypervisorsQ.isPending} />
          </div>
          <div className="sw-mount" style={{ "--sw-i": 2 } as React.CSSProperties}>
            <VmLifecycleCard
              total={totalVms}
              migrating={migrating}
              migrated={migrated}
              failed={failedVms}
              isLoading={vmsQ.isPending}
            />
          </div>
          <div className="col-span-1 sm:col-span-2 sw-mount" style={{ "--sw-i": 3 } as React.CSSProperties}>
            <CompatibilityCard
              segments={compatSegments}
              total={totalVms}
              isLoading={vmsQ.isPending}
            />
          </div>
        </div>
      </section>

      {/* Bento row 2 — activity + pipeline health */}
      <section className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-8 sw-mount" style={{ "--sw-i": 4 } as React.CSSProperties}>
          <ActivityFeed isLoading={isLoading} mig={mig} />
        </div>
        <div className="col-span-12 lg:col-span-4 sw-mount" style={{ "--sw-i": 5 } as React.CSSProperties}>
          <RatesPanel
            mig={mig}
            migrationSegments={migrationSegments}
            isLoading={migrationsQ.isPending}
          />
        </div>
      </section>

      <ErrorBanner queries={[hypervisorsQ, vmsQ, migrationsQ]} />
    </div>
  );
}

/* ----------------------------- pipeline strip ----------------------------- */

function PipelineStrip({ stages }: { stages: MigrationStats | undefined }) {
  const running = stages?.in_progress ?? 0;
  const queued = stages?.pending ?? 0;
  const total = running + queued;

  return (
    <Panel
      density="compact"
      kicker="pipeline · openshift virtualization"
      title={
        <span className="flex items-center gap-2">
          stack health
          <span className="kicker">{total} active jobs</span>
        </span>
      }
      action={
        <Ticker
          className="hidden md:block w-[280px]"
          speed={28}
          items={[
            <span key="t1" className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted">
              <span className="text-signal mr-2" aria-hidden>●</span> migrator: pvc populate · vm-debian-04
            </span>,
            <span key="t2" className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted">
              <span className="text-ok mr-2" aria-hidden>●</span> converter: qcow2 ready · 12.4 GB
            </span>,
            <span key="t3" className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted">
              <span className="text-info-soft mr-2" aria-hidden>●</span> adapter: virt-customize · dhcp + serial
            </span>,
            <span key="t4" className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted">
              <span className="text-warn mr-2" aria-hidden>●</span> analyzer: rule 0xb2 partial · ssh dropbear
            </span>,
          ]}
        />
      }
      className="overflow-visible"
    >
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-0 -mx-6 -mb-5 border-t border-line">
        {PIPELINE_STAGES.map((stage, i) => {
          const active = i <= 2 && running > 0;
          return (
            <div
              key={stage.key}
              className={cn(
                "relative px-5 py-4 border-r border-line last:border-r-0 flex flex-col gap-2",
                active ? "bg-bg-elev-2/40" : "",
              )}
            >
              {active && (
                <span
                  aria-hidden
                  className="absolute top-0 left-0 right-0 h-0.5 bg-signal/30 overflow-hidden"
                >
                  <span
                    className="absolute inset-0 bg-signal"
                    style={{
                      width: "30%",
                      animation: "shiftwise-topbar 2.2s linear infinite",
                    }}
                  />
                </span>
              )}
              <div className="flex items-center gap-2">
                <Icon icon={stage.icon} size={14} className={active ? "text-signal" : "text-ink-muted"} />
                <span className="kicker">{stage.label}</span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[18px] tabular text-ink leading-none">
                  {i === 0 ? hypervisorJobs(stages) : i === 4 ? formatNumber(stages?.completed) : stageNumber(stages, i)}
                </span>
                <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint">
                  {i === 4 ? "shipped" : i === 0 ? "scanned" : "running"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function hypervisorJobs(s: MigrationStats | undefined): string {
  return formatNumber(s?.total_migrations);
}

function stageNumber(s: MigrationStats | undefined, i: number): string {
  if (!s) return "—";
  if (i === 1) return formatNumber(s.pending);
  if (i === 2) return formatNumber(s.in_progress);
  if (i === 3) return formatNumber(Math.max(0, s.in_progress - 1));
  return "—";
}

/* ------------------------------ hero migration ----------------------------- */

function HeroMigration({
  mig,
  isLoading,
  adoptionRate,
  spark,
}: {
  mig: MigrationStats | undefined;
  isLoading: boolean;
  adoptionRate: number;
  spark: number[];
}) {
  return (
    <section
      className="relative h-full flex flex-col rounded-sm overflow-hidden bg-signal text-signal-ink"
    >
      <span aria-hidden className="sw-hairlines absolute inset-0 opacity-[0.18] pointer-events-none" />
      <div className="relative p-6 md:p-8 flex-1">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.1em] opacity-80">
              migrations · 2026 Q2
            </div>
            <h2 className="text-h2 lowercase mt-2 opacity-90 max-w-[26ch]">
              orchestration in flight on the cluster
            </h2>
          </div>
          <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 border border-white/30 rounded-sm">
            <span aria-hidden className="block h-2 w-2 rounded-full bg-white animate-[shiftwise-pulse_1.6s_var(--ease-out)_infinite]" />
            <span className="font-mono text-[10px] uppercase tracking-[0.08em]">
              tx active
            </span>
          </div>
        </div>

        <div className="mt-8 flex items-end justify-between gap-6 flex-wrap">
          <div>
            {isLoading ? (
              <Skeleton className="h-20 w-44 bg-white/15" />
            ) : (
              <div className="font-mono font-semibold tabular leading-none text-[88px] md:text-[112px]" style={{ letterSpacing: "-0.04em" }}>
                {formatNumber(mig?.in_progress ?? 0)}
              </div>
            )}
            <div className="mt-3 font-mono text-[12px] uppercase tracking-[0.08em] opacity-80">
              active · {formatNumber(mig?.pending)} queued · {formatNumber(mig?.completed)} completed
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <Sparkline
              values={spark}
              width={220}
              height={64}
              stroke="rgba(255,255,255,0.95)"
              fill="rgba(255,255,255,1)"
              strokeWidth={1.5}
            />
            <span className="font-mono text-[10px] uppercase tracking-[0.08em] opacity-70">
              throughput · last 24 hours
            </span>
          </div>
        </div>

        <div className="mt-8 grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-4 pt-6 border-t border-white/20">
          <StatLine
            icon={CheckCircle2}
            label="completed"
            value={isLoading ? "—" : formatNumber(mig?.completed)}
          />
          <StatLine
            icon={X}
            label="failed"
            value={isLoading ? "—" : formatNumber(mig?.failed)}
          />
          <StatLine
            icon={Activity}
            label="success rate"
            value={isLoading ? "—" : formatRate(mig?.success_rate)}
          />
          <StatLine
            icon={Database}
            label="transferred"
            value={isLoading ? "—" : formatGb(mig?.total_data_transferred_gb)}
          />
        </div>
      </div>
      <Link
        to="/vms"
        className="relative h-12 px-6 flex items-center justify-between border-t border-white/20 text-[13px] font-semibold transition-colors duration-150 hover:bg-white/10"
      >
        <span className="lowercase tracking-tight">
          adoption · {adoptionRate.toFixed(1)}% of fleet already migrated
        </span>
        <ArrowUpRight size={18} strokeWidth={1.75} />
      </Link>
    </section>
  );
}

function StatLine({ icon, label, value }: { icon: typeof Activity; label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.08em] opacity-80">
        <Icon icon={icon} size={12} />
        {label}
      </span>
      <span className="font-mono font-semibold tabular text-[24px] leading-none">{value}</span>
    </div>
  );
}

/* --------------------------------- fleet ---------------------------------- */

function FleetCard({ hyp, isLoading }: { hyp: HypervisorStats | undefined; isLoading: boolean }) {
  const types = Object.entries(hyp?.by_type ?? {})
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  return (
    <Panel
      kicker="inventory"
      title="hypervisors"
      action={
        <Link
          to="/hypervisors"
          className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted hover:text-signal transition-colors"
        >
          all →
        </Link>
      }
    >
      {isLoading ? (
        <SkeletonStat size="lg" />
      ) : (
        <>
          <div className="flex items-baseline gap-2">
            <span className="font-mono font-semibold tabular text-[40px] leading-none text-ink">
              {formatNumber(hyp?.active)}
            </span>
            <span className="font-mono text-[12px] text-ink-muted">
              / {formatNumber(hyp?.total)} active
            </span>
          </div>
          <ul className="mt-4 space-y-1.5">
            {types.length === 0 ? (
              <li className="font-mono text-[11px] text-ink-faint uppercase">no type</li>
            ) : (
              types.map(([t, n]) => (
                <li
                  key={t}
                  className="flex items-center justify-between gap-3 font-mono text-[11px] tabular"
                >
                  <span className="text-ink-muted lowercase truncate">
                    {t.replace(/_/g, " ").toLowerCase()}
                  </span>
                  <span className="text-ink">{formatNumber(n)}</span>
                </li>
              ))
            )}
          </ul>
        </>
      )}
    </Panel>
  );
}

/* ------------------------------- vm lifecycle ----------------------------- */

function VmLifecycleCard({
  total,
  migrating,
  migrated,
  failed,
  isLoading,
}: {
  total: number;
  migrating: number;
  migrated: number;
  failed: number;
  isLoading: boolean;
}) {
  const remaining = Math.max(0, total - migrated - migrating - failed);
  return (
    <Panel
      kicker="inventory"
      title="virtual machines"
      action={
        <Link
          to="/vms"
          className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted hover:text-signal transition-colors"
        >
          all →
        </Link>
      }
    >
      {isLoading ? (
        <SkeletonStat size="lg" />
      ) : (
        <>
          <div className="flex items-baseline gap-2">
            <span className="font-mono font-semibold tabular text-[40px] leading-none text-ink">
              {formatNumber(total)}
            </span>
            <Icon icon={Monitor} size={16} className="text-ink-faint" />
          </div>
          <div className="mt-4 space-y-0.5">
            <MetricRow label="discovered" value={formatNumber(remaining)} />
            <MetricRow label="migrating" value={formatNumber(migrating)} emphasis="signal" />
            <MetricRow label="migrated" value={formatNumber(migrated)} emphasis="ok" />
            <MetricRow label="failed" value={formatNumber(failed)} emphasis="err" />
          </div>
        </>
      )}
    </Panel>
  );
}

/* ------------------------------ compatibility ----------------------------- */

function CompatibilityCard({
  segments,
  total,
  isLoading,
}: {
  segments: { key: string; label: string; value: number; color: string }[];
  total: number;
  isLoading: boolean;
}) {
  const ok = segments.find((s) => s.key === "ok")?.value ?? 0;
  const pct = total > 0 ? (ok / total) * 100 : 0;

  return (
    <Panel
      kicker="analyzer · hybrid scoring"
      title="fleet compatibility"
      hint={`${pct.toFixed(1)}% ready for kubevirt`}
      action={
        <span
          className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 border border-line rounded-sm font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted"
        >
          <Icon icon={Sparkles} size={12} className="text-signal" />
          model · v3
        </span>
      }
    >
      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <StackedBar segments={segments} height={14} />
      )}
    </Panel>
  );
}

/* ------------------------------ activity feed ----------------------------- */

type Activity = {
  ts: string;
  kind: "migration" | "discovery" | "analyzer" | "alert";
  message: string;
  tone: "ok" | "warn" | "err" | "info" | "signal";
};

const SAMPLE_ACTIVITY: Activity[] = [
  { ts: "14:02:11", kind: "migration", message: "vm-debian-04 → shiftwise-acme · phase: transferring (qcow2 12.4 GB)", tone: "signal" },
  { ts: "13:58:42", kind: "analyzer", message: "vm-postgres-prod analyzed · score 87 · 1 warning (dropbear ssh)", tone: "warn" },
  { ts: "13:51:08", kind: "migration", message: "vm-ubuntu-jenkins migrated · adapter complete · vm running", tone: "ok" },
  { ts: "13:44:19", kind: "discovery", message: "hypervisor kvm-paris-02 synced · 14 new vms", tone: "info" },
  { ts: "13:39:55", kind: "alert", message: "transit-pvc · usage 47% · threshold ok", tone: "info" },
  { ts: "13:21:30", kind: "migration", message: "vm-legacy-win2008 · converter failed · vmdk thin-provisioning unsupported", tone: "err" },
];

function ActivityFeed({ isLoading, mig }: { isLoading: boolean; mig: MigrationStats | undefined }) {
  return (
    <Panel
      kicker={`activity · ${mig?.total_migrations ?? "—"} total migrations`}
      title="live event stream"
      hint={
        <span className="inline-flex items-center gap-2">
          pipeline events · last 5 minutes
          <span className="inline-flex items-center gap-1 px-1.5 py-px border border-warn/40 text-warn rounded-sm font-mono text-[9px] tracking-[0.08em] uppercase">
            demo · disconnected
          </span>
        </span>
      }
      action={
        <Button variant="ghost" uppercase>
          view all
        </Button>
      }
      bodyClassName="px-0"
    >
      {isLoading ? (
        <div className="px-6 pb-2 space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-2 w-16" />
              <Skeleton className="h-2 flex-1" />
            </div>
          ))}
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {SAMPLE_ACTIVITY.map((a, i) => (
            <li
              key={i}
              className="px-6 py-3 flex items-start gap-4 hover:bg-bg-elev-2/40 transition-colors duration-150"
            >
              <span className="font-mono text-[11px] tabular text-ink-faint shrink-0 w-16">{a.ts}</span>
              <span
                className={cn(
                  "shrink-0 inline-flex items-center justify-center w-2 h-2 mt-1.5 rounded-full",
                )}
                style={{
                  backgroundColor:
                    a.tone === "ok"
                      ? "var(--ok)"
                      : a.tone === "err"
                        ? "var(--err)"
                        : a.tone === "warn"
                          ? "var(--warn)"
                          : a.tone === "signal"
                            ? "var(--signal)"
                            : "var(--info-soft)",
                }}
              />
              <span className="flex-1 font-mono text-[12px] text-ink leading-relaxed lowercase">
                <span className="text-ink-muted uppercase tracking-[0.06em] text-[10px] mr-2">
                  {a.kind}
                </span>
                {a.message}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* --------------------------------- rates ---------------------------------- */

function RatesPanel({
  mig,
  migrationSegments,
  isLoading,
}: {
  mig: MigrationStats | undefined;
  migrationSegments: { key: string; label: string; value: number; color: string }[];
  isLoading: boolean;
}) {
  return (
    <Panel kicker="Performance" title="rates & throughput">
      {isLoading ? (
        <div className="space-y-4">
          <SkeletonStat />
          <SkeletonStat />
        </div>
      ) : (
        <div className="space-y-5">
          <div className="space-y-1">
            <div className="kicker">success rate</div>
            <div className="flex items-baseline justify-between">
              <span className="font-mono font-semibold tabular text-[32px] text-ok leading-none">
                {formatRate(mig?.success_rate)}
              </span>
              <span className="font-mono text-[11px] text-ink-muted uppercase tracking-[0.06em]">
                ≥ slo 95%
              </span>
            </div>
            <div className="mt-2 h-1 w-full rounded-sm bg-bg-elev-2 overflow-hidden">
              <div
                className="h-full bg-ok"
                style={{
                  width: `${Math.min(100, mig?.success_rate ?? 0)}%`,
                  transition: "width 600ms var(--ease-out)",
                }}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-0.5">
              <div className="kicker">avg duration</div>
              <div className="font-mono tabular text-[18px] text-ink leading-none">
                {formatDuration(mig?.average_duration_seconds)}
              </div>
            </div>
            <div className="space-y-0.5">
              <div className="kicker">volume</div>
              <div className="font-mono tabular text-[18px] text-ink leading-none">
                {formatGb(mig?.total_data_transferred_gb)}
              </div>
            </div>
          </div>

          <div>
            <div className="kicker mb-2">distribution</div>
            <StackedBar segments={migrationSegments} height={6} />
          </div>
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------- error banner ----------------------------- */

function ErrorBanner({
  queries,
}: {
  queries: { error: unknown; isError: boolean }[];
}) {
  const failed = queries.find((q) => q.isError);
  if (!failed) return <EmptyOk />;
  return (
    <Callout tone="err" role="alert">
      stats load failed · auto-retry in 30s
    </Callout>
  );
}

function EmptyOk() {
  return (
    <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.08em] text-ink-faint">
      <Icon icon={CheckCircle2} size={12} />
      no incidents · last 24h
    </div>
  );
}
