import { useQuery } from "@tanstack/react-query";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { KPISecondary } from "@/components/ui/KPISecondary";
import { StatBlock } from "@/components/ui/StatBlock";
import { Activity, Database, HardDrive, Server } from "lucide-react";
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
  const migrated = vm?.by_status.MIGRATED ?? 0;

  return (
    <div className="max-w-[1440px] mx-auto p-8 space-y-12">
      <section className="grid gap-6 grid-cols-12">
        <div className="col-span-12 lg:col-span-7">
          <KPIPrimary
            label="migrations"
            value={formatNumber(mig?.in_progress)}
            tone="signal"
            headline={
              mig
                ? `${formatNumber(mig.in_progress)} en cours · ${formatNumber(mig.pending)} en file`
                : "chargement…"
            }
          >
            <div className="grid grid-cols-2 gap-6 mt-2">
              <StatBlock
                icon={Activity}
                label="terminées"
                value={formatNumber(mig?.completed)}
              />
              <StatBlock
                icon={HardDrive}
                label="échouées"
                value={formatNumber(mig?.failed)}
              />
              <StatBlock
                icon={Database}
                label="taux succès"
                value={formatRate(mig?.success_rate)}
              />
              <StatBlock
                icon={Server}
                label="transféré"
                value={formatGb(mig?.total_data_transferred_gb)}
              />
            </div>
          </KPIPrimary>
        </div>

        <div className="col-span-12 lg:col-span-5 grid grid-cols-1 sm:grid-cols-3 gap-4 lg:grid-cols-1 xl:grid-cols-3 content-start">
          <KPISecondary
            label="hyperviseurs actifs"
            value={formatNumber(hyp?.active)}
            suffix={hyp ? `/ ${formatNumber(hyp.total)}` : undefined}
          />
          <KPISecondary
            label="vms découvertes"
            value={formatNumber(vm?.total)}
          />
          <KPISecondary
            label="vms migrées"
            value={formatNumber(migrated)}
          />
        </div>
      </section>

      <section>
        <h2 className="text-h2 lowercase mb-4">compatibilité</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <CompatRow label="compatible" value={compatible} tone="ok" />
          <CompatRow label="partiel" value={partial} tone="warn" />
          <CompatRow label="incompatible" value={incompatible} tone="err" />
        </div>
      </section>

      <ErrorBanner
        queries={[hypervisorsQ, vmsQ, migrationsQ]}
      />
    </div>
  );
}

type CompatTone = "ok" | "warn" | "err";

function CompatRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: CompatTone;
}) {
  const color =
    tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : "var(--err)";
  return (
    <div className="border border-line bg-bg-elev p-6 flex flex-col gap-3">
      <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
        {label}
      </span>
      <span className="text-major tabular leading-none" style={{ color }}>
        {formatNumber(value)}
      </span>
    </div>
  );
}

function ErrorBanner({
  queries,
}: {
  queries: { error: unknown; isError: boolean }[];
}) {
  const failed = queries.find((q) => q.isError);
  if (!failed) return null;
  return (
    <div
      role="alert"
      className="border border-err text-err bg-bg-elev-2 px-4 py-3 font-mono text-[11px] uppercase tracking-[0.04em]"
    >
      Erreur lors du chargement des statistiques. Réessai automatique dans 30s.
    </div>
  );
}
