import { Cpu, Plug, RefreshCw, Rocket, ScanSearch } from "lucide-react";
import type { PipelineStageData } from "@/components/PipelineStrip";
import type { MigrationStats } from "@/api/stats";
import { formatNumber } from "@/lib/format";

/**
 * One-line description of each pipeline stage, shown before any migration has
 * run so the empty pipeline reads as a diagram rather than dead tiles.
 */
const STAGE_BLURB: Record<string, string> = {
  discover: "Scans hypervisors for VMs",
  analyze: "Scores OpenShift fit",
  convert: "Disks to QCOW2",
  adapt: "Guest OS fixups",
  migrate: "Boots on KubeVirt",
};

/**
 * Single source of truth for the five-stage migration pipeline strip.
 *
 * Both the Dashboard and the Migrations page render this exact shape so the
 * two views can never drift. Stage state is driven by *live* activity, not
 * cumulative totals: convert/adapt/migrate are "active" only while a migration
 * is genuinely in flight (`in_progress > 0`); once nothing is running they
 * settle to "done" (if there is completed throughput) or "pending".
 */
export function buildMigrationPipelineStages(
  stats: MigrationStats,
): PipelineStageData[] {
  const total = stats.total_migrations;
  const completed = stats.completed;
  const inProgress = stats.in_progress;
  const pending = stats.pending;
  const succeededOrInflight = completed + inProgress;
  const anyInflight = inProgress > 0;

  return [
    {
      key: "discover",
      label: "Discovery",
      icon: ScanSearch,
      count: formatNumber(total),
      meta: total > 0 ? "100% scanned" : STAGE_BLURB.discover,
      progress: total > 0 ? 100 : 0,
      state: total > 0 ? "done" : "pending",
    },
    {
      key: "analyze",
      label: "Analyzer",
      icon: Cpu,
      count: formatNumber(succeededOrInflight + pending),
      meta: total > 0 ? "100% analyzed" : STAGE_BLURB.analyze,
      progress: total > 0 ? 100 : 0,
      state: total > 0 ? "done" : "pending",
    },
    {
      key: "convert",
      label: "Converter",
      icon: RefreshCw,
      count: formatNumber(succeededOrInflight),
      meta:
        total > 0
          ? `${Math.round((succeededOrInflight / total) * 100)}% converted`
          : STAGE_BLURB.convert,
      progress: total > 0 ? (succeededOrInflight / total) * 100 : 0,
      state: anyInflight ? "active" : succeededOrInflight > 0 ? "done" : "pending",
    },
    {
      key: "adapt",
      label: "Adapter",
      icon: Plug,
      count: formatNumber(inProgress),
      meta:
        total > 0
          ? `${Math.round((inProgress / total) * 100)}% adapted`
          : STAGE_BLURB.adapt,
      progress: total > 0 ? (inProgress / total) * 100 : 0,
      state: anyInflight ? "active" : completed > 0 ? "done" : "pending",
    },
    {
      key: "migrate",
      label: "Migrator",
      icon: Rocket,
      count: formatNumber(completed),
      meta:
        total > 0
          ? `${Math.round((completed / total) * 100)}% migrated`
          : STAGE_BLURB.migrate,
      progress: total > 0 ? (completed / total) * 100 : 0,
      state: anyInflight ? "active" : completed > 0 ? "done" : "pending",
    },
  ];
}
