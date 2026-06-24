import { api } from "@/lib/axios";
import type { Paginated } from "@/api/types";

export const VM_STATUSES = [
  "discovered",
  "analyzing",
  "compatible",
  "incompatible",
  "partial",
  "migrating",
  "migrated",
  "failed",
  "archived",
] as const;

export const COMPATIBILITY_STATUSES = [
  "compatible",
  "partial",
  "incompatible",
  "unknown",
] as const;

export type VmStatus = (typeof VM_STATUSES)[number];
export type CompatibilityStatus = (typeof COMPATIBILITY_STATUSES)[number];

// Mirrors a single rule result from the backend rules engine
// (`compatibility_rules.py`): keyed by `id`, severity is UPPERCASE.
export type CompatibilityRule = {
  id: string;
  passed: boolean;
  severity: "BLOCKER" | "WARNING" | "INFO";
  message: string;
  weight: number;
};

export type CompatibilityDetails = {
  score: number;
  grade: "COMPATIBLE" | "PARTIAL" | "INCOMPATIBLE";
  engine: "rules" | "model";
  confidence: number | null;
  model_grade: string | null;
  override_reason: string | null;
  rules: CompatibilityRule[];
  // `aggregate()` returns these as plain message strings, not rule objects.
  blockers: string[];
  warnings: string[];
  analyzed_at: string;
};

export type Vm = {
  id: number;
  name: string;
  description: string | null;
  cpu_cores: number;
  memory_mb: number;
  disk_gb: number;
  os_type: string;
  os_version: string | null;
  os_name: string | null;
  source_hypervisor_id: number | null;
  source_uuid: string | null;
  source_name: string | null;
  ip_address: string | null;
  mac_address: string | null;
  hostname: string | null;
  status: VmStatus;
  compatibility_status: CompatibilityStatus;
  compatibility_details: CompatibilityDetails | null;
  openshift_vm_name: string | null;
  openshift_namespace: string | null;
  openshift_node: string | null;
  discovered_at: string | null;
  last_seen_at: string | null;
  tags: Record<string, unknown> | null;
  custom_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  is_compatible: boolean;
  is_migrated: boolean;
  can_migrate: boolean;
};

export type VmListResponse = Paginated<Vm>;

export type ListVmsParams = {
  skip?: number;
  limit?: number;
  status?: VmStatus;
  compatibility?: CompatibilityStatus;
  hypervisor_id?: number;
  search?: string;
};

export async function listVms(params: ListVmsParams = {}): Promise<VmListResponse> {
  const res = await api.get<VmListResponse>("/vms", { params });
  return res.data;
}

export async function getVm(id: number): Promise<Vm> {
  const res = await api.get<Vm>(`/vms/${id}`);
  return res.data;
}

export async function analyzeVm(id: number, force = true): Promise<Vm> {
  const res = await api.post<Vm>(`/vms/${id}/analyze`, null, {
    params: { force },
  });
  return res.data;
}
