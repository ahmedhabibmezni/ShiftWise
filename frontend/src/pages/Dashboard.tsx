import { useMemo } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Plug,
  RefreshCw,
  Rocket,
  ScanSearch,
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
import {
  MigrationStatusBadge,
  type MigrationStatusKey,
} from "@/components/ui/StatusBadge";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { formatRelativeTime } from "@/lib/format";
import {
  fetchHypervisorStats,
  fetchMigrationStats,
  fetchVmStats,
  type HypervisorStats,
  type MigrationStats,
  type VmStats,
} from "@/api/stats";
import {
  listHypervisors,
  type Hypervisor,
  type HypervisorListResponse,
} from "@/api/hypervisors";
import {
  listMigrations,
  type Migration,
  type MigrationListResponse,
} from "@/api/migrations";

const REFETCH_INTERVAL_MS = 30_000;

function formatNumber(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US");
}

/** Adoption percentage: migrated / discovered, clamped to 0–100. */
function adoptionPercent(discovered: number, migrated: number): number {
  if (discovered <= 0) return 0;
  return Math.min(100, Math.round((migrated / discovered) * 100));
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
  // Real per-host figures for the Hypervisors table and the recent-activity
  // feed — both previously rendered fabricated numbers.
  const hypervisorListQ = useQuery<HypervisorListResponse>({
    queryKey: ["dashboard", "hypervisor-list"],
    queryFn: () => listHypervisors({ limit: 50 }),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const recentMigrationsQ = useQuery<MigrationListResponse>({
    queryKey: ["dashboard", "recent-migrations"],
    queryFn: () => listMigrations({ limit: 6 }),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const hyp = hypervisorsQ.data;
  const vm = vmsQ.data;
  const mig = migrationsQ.data;

  const compatible = vm?.by_compatibility.COMPATIBLE ?? 0;
  const totalVms = vm?.total ?? 0;
  const failedMigrations = mig?.failed ?? 0;
  const activeMigs = mig?.in_progress ?? 0;
  const migratedVms = vm?.by_status.MIGRATED ?? 0;

  // Build pipeline stage data from live counts
  const pipelineStages: PipelineStageData[] = useMemo(() => {
    const discovered = totalVms;
    const analysed =
      compatible +
      (vm?.by_compatibility.PARTIAL ?? 0) +
      (vm?.by_compatibility.INCOMPATIBLE ?? 0);
    const migrating = activeMigs + (mig?.pending ?? 0);
    const adapted = mig?.in_progress ?? 0;
    const migrated = migratedVms;
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
        meta:
          discovered > 0
            ? `${Math.round((analysed / discovered) * 100)}% analysed`
            : "—",
        progress: discovered > 0 ? (analysed / discovered) * 100 : 0,
        state:
          analysed === discovered && discovered > 0
            ? "done"
            : analysed > 0
              ? "active"
              : "pending",
      },
      {
        key: "convert",
        label: "Converter",
        icon: RefreshCw,
        count: formatNumber(migrating),
        meta:
          discovered > 0
            ? `${Math.round((migrating / Math.max(1, discovered)) * 100)}% converted`
            : "—",
        progress: discovered > 0 ? (migrating / Math.max(1, discovered)) * 100 : 0,
        state: migrating > 0 ? "active" : "pending",
      },
      {
        key: "adapt",
        label: "Adapter",
        icon: Plug,
        count: formatNumber(adapted),
        meta:
          discovered > 0
            ? `${Math.round((adapted / Math.max(1, discovered)) * 100)}% adapted`
            : "—",
        progress: discovered > 0 ? (adapted / Math.max(1, discovered)) * 100 : 0,
        state: adapted > 0 ? "active" : "pending",
      },
      {
        key: "migrate",
        label: "Migrator",
        icon: Rocket,
        count: formatNumber(migrated),
        meta:
          discovered > 0
            ? `${Math.round((migrated / Math.max(1, discovered)) * 100)}% migrated`
            : "—",
        progress: discovered > 0 ? (migrated / Math.max(1, discovered)) * 100 : 0,
        state: migrated > 0 ? "active" : "pending",
      },
    ];
  }, [totalVms, compatible, vm, mig, activeMigs, migratedVms]);

  const adoptionPct = adoptionPercent(totalVms, migratedVms);

  const queries = [
    hypervisorsQ,
    vmsQ,
    migrationsQ,
    hypervisorListQ,
    recentMigrationsQ,
  ];
  const hasError = queries.some((q) => q.isError);

  return (
    <div className="glass-budget-lite flex flex-col gap-6">
      {hasError && (
        <Callout tone="err" role="alert">
          Could not load dashboard data. Retrying every{" "}
          {REFETCH_INTERVAL_MS / 1000}s.
        </Callout>
      )}

      {/* ===== KPI ROW ===== */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPIPrimary
          label="VMs Discovered"
          value={<CountUp value={totalVms} />}
          icon={ScanSearch}
          iconTone="accent"
        />
        <KPIPrimary
          label="Compatible VMs"
          value={<CountUp value={compatible} />}
          icon={CheckCircle2}
          iconTone="blue"
        />
        <KPIPrimary
          label="Active Migrations"
          value={<CountUp value={activeMigs} />}
          icon={Rocket}
          iconTone="accent"
        />
        <KPIPrimary
          label="Failed Migrations"
          value={<CountUp value={failedMigrations} />}
          icon={AlertTriangle}
          iconTone="warn"
        />
      </section>

      {/* ===== ROW 2: HERO + READINESS + FLEET HEALTH ===== */}
      <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <HeroWelcome
          name={user?.full_name?.trim() || user?.username || "Operator"}
          description="Track hypervisor discovery, compatibility analysis, and migrations to OpenShift Virtualization from one place."
          cta="Start a migration"
          ctaTo="/migrations"
        />

        <Panel
          title="Readiness Score"
          hint="Reachable hypervisors"
          bodyClassName="flex flex-col items-center justify-center"
        >
          <div className="flex flex-col items-center gap-3 mt-2">
            <ReadinessGauge
              value={
                hyp
                  ? Math.round(
                      ((hyp.active || 0) / Math.max(1, hyp.total || 1)) * 100,
                    )
                  : 0
              }
            />
            <div className="flex justify-between w-full max-w-[280px] text-[11px] font-medium text-[var(--text-secondary)] px-3">
              <span>0%</span>
              <span>100%</span>
            </div>
          </div>
        </Panel>

        <Panel
          title="Fleet Health"
          hint="Migration adoption"
          bodyClassName="grid grid-cols-[1fr_auto] gap-5 items-center"
        >
          <div className="flex flex-col gap-3">
            <FleetStatRow
              label="Migrated"
              value={<CountUp value={migratedVms} />}
            />
            <FleetStatRow
              label="Pending"
              value={<CountUp value={(mig?.pending ?? 0) + activeMigs} />}
            />
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
        hint={`${hyp?.total ?? 0} hypervisors in scope`}
      >
        {migrationsQ.isPending || vmsQ.isPending ? (
          <Skeleton className="h-[120px] w-full" />
        ) : (
          <PipelineStrip stages={pipelineStages} />
        )}
      </Panel>

      {/* ===== ROW 4: HYPERVISORS TABLE + ACTIVITY ===== */}
      <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <HypervisorsCard
          hypervisors={hypervisorListQ.data?.items}
          isPending={hypervisorListQ.isPending}
          activeCount={hyp?.active}
          className="xl:col-span-2"
        />
        <ActivityCard
          migrations={recentMigrationsQ.data?.items}
          isPending={recentMigrationsQ.isPending}
        />
      </section>
    </div>
  );
}

function FleetStatRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="bg-[var(--surface-soft)] rounded-2xl px-4 py-3.5">
      <div className="text-[11px] text-[var(--text-secondary)] font-medium">
        {label}
      </div>
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
  vmware_workstation: ["vWS", "#1F3F8A", "#3E6FD4"],
  vsphere: ["vSp", "#1F3F8A", "#3E6FD4"],
  vmware_esxi: ["ESX", "#1F3F8A", "#3E6FD4"],
  kvm: ["KVM", "#812300", "#FF7A2F"],
  hyper_v: ["H-V", "#4A7FC4", "#2651B2"],
  proxmox: ["Px", "#1F9D6A", "#2ECC8A"],
  ovirt: ["oVi", "#3E6FD4", "#1F3F8A"],
  virtualbox: ["VBx", "#4A546E", "#8893B0"],
  xen: ["Xen", "#2651B2", "#4A7FC4"],
  other: ["?", "#4A546E", "#8893B0"],
};

function HypervisorsCard({
  hypervisors,
  isPending,
  activeCount,
  className,
}: {
  hypervisors: Hypervisor[] | undefined;
  isPending: boolean;
  activeCount: number | undefined;
  className?: string;
}) {
  // Top hosts by discovered VM count — every figure is read straight off the
  // hypervisor record (no synthetic multipliers).
  const rows = (hypervisors ?? [])
    .slice()
    .sort((a, b) => b.total_vms_discovered - a.total_vms_discovered)
    .slice(0, 5);

  return (
    <Panel
      title="Hypervisors"
      hint={
        activeCount !== undefined ? (
          <span>
            <span className="text-[var(--alert-success-light)] font-bold">
              {activeCount} active
            </span>{" "}
            connection{activeCount === 1 ? "" : "s"}
          </span>
        ) : undefined
      }
      className={className}
    >
      {isPending ? (
        <Skeleton className="h-[220px] w-full mt-4" />
      ) : rows.length === 0 ? (
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
            {rows.map((h) => {
              const [badge, c1, c2] =
                HYPERVISOR_BADGE_COLORS[h.type] ??
                HYPERVISOR_BADGE_COLORS.other;
              const pct = adoptionPercent(
                h.total_vms_discovered,
                h.total_vms_migrated,
              );
              return (
                <TR key={h.id}>
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
                          {h.name}
                        </div>
                        <div className="text-[11px] text-[var(--text-muted)]">
                          {h.type.replace(/_/g, " ")}
                        </div>
                      </div>
                    </div>
                  </TD>
                  <TD numeric className="font-bold">
                    {formatNumber(h.total_vms_discovered)}
                  </TD>
                  <TD numeric className="font-bold">
                    {formatNumber(h.total_vms_migrated)}
                  </TD>
                  <TD numeric>
                    <div className="inline-flex items-center gap-3">
                      <span className="text-[12px] tabular font-bold text-[var(--text-primary)]">
                        {pct}%
                      </span>
                      <span
                        className="block w-[80px] h-1 rounded-full overflow-hidden"
                        style={{ background: "var(--surface-soft-strong)" }}
                      >
                        <span
                          className="block h-full rounded-full"
                          style={{
                            width: `${pct}%`,
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

function ActivityCard({
  migrations,
  isPending,
}: {
  migrations: Migration[] | undefined;
  isPending: boolean;
}) {
  const entries = migrations ?? [];

  return (
    <Panel title="Recent Migrations" hint="Latest pipeline activity">
      {isPending ? (
        <Skeleton className="h-[240px] w-full mt-5" />
      ) : entries.length === 0 ? (
        <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">
          No migrations yet.
        </div>
      ) : (
        <div className="relative mt-5 flex flex-col gap-5">
          <span
            aria-hidden
            className="absolute left-4 top-3 bottom-3 w-px"
            style={{ background: "var(--hairline)" }}
          />
          {entries.map((m) => (
            <div
              key={m.id}
              className="grid grid-cols-[32px_1fr] gap-3.5 items-start"
            >
              <span
                className="glass-card relative z-[1] w-8 h-8 rounded-[9px] grid place-items-center"
                aria-hidden
              >
                <Rocket
                  size={14}
                  strokeWidth={2}
                  className="text-[var(--accent-light)]"
                />
              </span>
              <div className="flex flex-col gap-1 pt-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-bold text-[var(--text-primary)] leading-tight">
                    {m.target_vm_name?.trim() || `Migration #${m.id}`}
                  </span>
                  <MigrationStatusBadge
                    status={
                      m.status.toUpperCase() as MigrationStatusKey
                    }
                  />
                </div>
                <div className="text-[11px] text-[var(--text-muted)]">
                  {m.current_step ?? "—"} · {formatRelativeTime(m.updated_at)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
