import { api } from "@/lib/axios";

export const MIGRATION_STATUSES = [
  "pending",
  "validating",
  "preparing",
  "transferring",
  "configuring",
  "starting",
  "verifying",
  "completed",
  "failed",
  "cancelled",
  "rollback",
  "rolled_back",
] as const;

export const MIGRATION_STRATEGIES = [
  "direct",
  "conversion",
  "hybrid",
  "cold",
  "warm",
  "auto",
] as const;

export type MigrationStatus = (typeof MIGRATION_STATUSES)[number];
export type MigrationStrategy = (typeof MIGRATION_STRATEGIES)[number];

/** Title-cases a strategy enum value for display (the API stores them lowercase). */
export function formatStrategy(strategy: MigrationStrategy): string {
  return strategy.charAt(0).toUpperCase() + strategy.slice(1);
}

/**
 * Statuses where the worker is actively progressing the migration.
 * Mirrors `Migration.is_active` on the backend model.
 */
export const ACTIVE_MIGRATION_STATUSES: ReadonlySet<MigrationStatus> = new Set([
  "pending",
  "validating",
  "preparing",
  "transferring",
  "configuring",
  "starting",
  "verifying",
]);

export type Migration = {
  id: number;
  vm_id: number;
  status: MigrationStatus;
  strategy: MigrationStrategy;
  target_namespace: string;
  target_storage_class: string;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  progress_percentage: number;
  current_step: string | null;
  current_step_number: number;
  total_steps: number;
  success: boolean | null;
  error_message: string | null;
  error_code: string | null;
  migration_config: Record<string, unknown> | null;
  source_size_gb: number | null;
  transferred_gb: number;
  transfer_rate_mbps: number | null;
  target_vm_name: string | null;
  target_node: string | null;
  requires_conversion: boolean;
  conversion_format: string | null;
  conversion_started_at: string | null;
  conversion_completed_at: string | null;
  pre_migration_checks: Record<string, unknown> | null;
  post_migration_checks: Record<string, unknown> | null;
  can_rollback: boolean;
  tags: Record<string, unknown> | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  is_active: boolean;
  is_completed: boolean;
  duration_seconds: number;
  estimated_time_remaining_seconds: number;
};

export type MigrationListResponse = {
  total: number;
  items: Migration[];
  page: number;
  page_size: number;
};

export type ListMigrationsParams = {
  skip?: number;
  limit?: number;
  status?: MigrationStatus;
  strategy?: MigrationStrategy;
  vm_id?: number;
};

export async function listMigrations(
  params: ListMigrationsParams = {},
): Promise<MigrationListResponse> {
  const res = await api.get<MigrationListResponse>("/migrations", { params });
  return res.data;
}

export async function getMigration(id: number): Promise<Migration> {
  const res = await api.get<Migration>(`/migrations/${id}`);
  return res.data;
}

export type CreateMigrationPayload = {
  vm_id: number;
  strategy: MigrationStrategy;
  target_storage_class?: string;
  scheduled_at?: string | null;
  notes?: string | null;
};

export async function createMigration(
  payload: CreateMigrationPayload,
): Promise<Migration> {
  const res = await api.post<Migration>("/migrations", payload);
  return res.data;
}

export async function startMigration(id: number): Promise<Migration> {
  const res = await api.post<Migration>(`/migrations/${id}/start`);
  return res.data;
}

export async function cancelMigration(
  id: number,
  reason?: string,
): Promise<Migration> {
  const res = await api.post<Migration>(`/migrations/${id}/cancel`, {
    reason: reason ?? null,
  });
  return res.data;
}

export async function deleteMigration(id: number): Promise<void> {
  await api.delete(`/migrations/${id}`);
}
