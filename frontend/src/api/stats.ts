import { api } from "@/lib/axios";

export type HypervisorStats = {
  total: number;
  active: number;
  inactive: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
};

export type VmStats = {
  total: number;
  by_status: Record<string, number>;
  by_compatibility: Record<string, number>;
};

export type MigrationStats = {
  total_migrations: number;
  completed: number;
  failed: number;
  in_progress: number;
  pending: number;
  success_rate: number;
  average_duration_seconds: number | null;
  total_data_transferred_gb: number;
};

export async function fetchHypervisorStats(): Promise<HypervisorStats> {
  const res = await api.get<HypervisorStats>("/hypervisors/stats/summary");
  return res.data;
}

export async function fetchVmStats(): Promise<VmStats> {
  const res = await api.get<VmStats>("/vms/stats/summary");
  return res.data;
}

export async function fetchMigrationStats(): Promise<MigrationStats> {
  const res = await api.get<MigrationStats>("/migrations/stats/summary");
  return res.data;
}
