import { api } from "@/lib/axios";

export const HYPERVISOR_TYPES = [
  "vsphere",
  "vmware_workstation",
  "vmware_esxi",
  "hyper_v",
  "kvm",
  "proxmox",
  "ovirt",
  "virtualbox",
  "xen",
  "other",
] as const;

export const HYPERVISOR_STATUSES = [
  "active",
  "inactive",
  "error",
  "unreachable",
  "authenticating",
  "discovering",
  "unknown",
] as const;

export type HypervisorType = (typeof HYPERVISOR_TYPES)[number];
export type HypervisorStatus = (typeof HYPERVISOR_STATUSES)[number];

export type Hypervisor = {
  id: number;
  name: string;
  description: string | null;
  type: HypervisorType;
  host: string;
  port: number | null;
  username: string;
  verify_ssl: boolean;
  status: HypervisorStatus;
  is_active: boolean;
  last_sync_at: string | null;
  last_successful_connection: string | null;
  last_error: string | null;
  total_vms_discovered: number;
  total_vms_migrated: number;
  connection_config: Record<string, unknown> | null;
  tags: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  is_reachable: boolean;
  connection_url: string;
  needs_sync: boolean;
};

export type HypervisorListResponse = {
  total: number;
  items: Hypervisor[];
  page: number;
  page_size: number;
};

export type ListHypervisorsParams = {
  skip?: number;
  limit?: number;
  type?: HypervisorType;
  status?: HypervisorStatus;
  is_active?: boolean;
  search?: string;
};

export async function listHypervisors(
  params: ListHypervisorsParams = {},
): Promise<HypervisorListResponse> {
  const res = await api.get<HypervisorListResponse>("/hypervisors", { params });
  return res.data;
}

export async function getHypervisor(id: number): Promise<Hypervisor> {
  const res = await api.get<Hypervisor>(`/hypervisors/${id}`);
  return res.data;
}

export type CreateHypervisorPayload = {
  name: string;
  description?: string | null;
  type: HypervisorType;
  host: string;
  port?: number | null;
  username: string;
  password: string;
  verify_ssl: boolean;
};

export async function createHypervisor(
  payload: CreateHypervisorPayload,
): Promise<Hypervisor> {
  const res = await api.post<Hypervisor>("/hypervisors", payload);
  return res.data;
}

export type UpdateHypervisorPayload = {
  name?: string;
  description?: string | null;
  host?: string;
  port?: number | null;
  username?: string;
  password?: string;
  verify_ssl?: boolean;
  is_active?: boolean;
};

export async function updateHypervisor(
  id: number,
  payload: UpdateHypervisorPayload,
): Promise<Hypervisor> {
  const res = await api.put<Hypervisor>(`/hypervisors/${id}`, payload);
  return res.data;
}

export async function deleteHypervisor(id: number): Promise<void> {
  await api.delete(`/hypervisors/${id}`);
}

export type TestConnectionPayload = {
  type: HypervisorType;
  host: string;
  port?: number | null;
  username: string;
  password: string;
  verify_ssl: boolean;
};

export type TestConnectionResult = {
  success: boolean;
  message: string;
  vms_count: number | null;
  error: string | null;
};

export async function testHypervisorConnection(
  payload: TestConnectionPayload,
): Promise<TestConnectionResult> {
  const res = await api.post<TestConnectionResult>(
    "/hypervisors/test-connection",
    payload,
  );
  return res.data;
}

export type SyncResponse = {
  hypervisor_id: number;
  hypervisor_name: string;
  status: string;
  message: string;
  statistics: {
    total_discovered: number;
    new_vms: number;
    updated_vms: number;
    archived_vms: number;
    errors: string[];
  };
};

export async function syncHypervisor(id: number): Promise<SyncResponse> {
  const res = await api.post<SyncResponse>(`/hypervisors/${id}/sync`);
  return res.data;
}

export type HypervisorVm = {
  id: number;
  name: string;
  status: string;
  compatibility_status: string;
  os_type: string;
  cpu_cores: number;
  memory_mb: number;
  disk_gb: number;
  ip_address: string | null;
};

export type HypervisorVmsResponse = {
  hypervisor_id: number;
  hypervisor_name: string;
  total_vms: number;
  vms: HypervisorVm[];
};

export async function listHypervisorVms(id: number): Promise<HypervisorVmsResponse> {
  const res = await api.get<HypervisorVmsResponse>(`/hypervisors/${id}/vms`);
  return res.data;
}
