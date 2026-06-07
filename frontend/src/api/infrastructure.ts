import { api } from "@/lib/axios";

// Mirrors backend ClusterMode / ClusterScopeType / ClusterHealthStatus enums
// (member NAMES lowercased to their .value form on the wire).
export const CLUSTER_MODES = ["kubeconfig", "incluster", "custom"] as const;
export type ClusterMode = (typeof CLUSTER_MODES)[number];

export type ClusterScopeType = "platform_default" | "tenant";

export type ClusterHealthStatus =
  | "healthy"
  | "degraded"
  | "unreachable"
  | "auth_failed"
  | "invalid"
  | "unknown";

// Read model — NEVER carries a secret (no kubeconfig content, no token).
export type ClusterConfigRead = {
  scope_type: ClusterScopeType;
  tenant_id: string | null;
  mode: ClusterMode;
  has_credentials: boolean;
  api_url: string | null;
  verify_ssl: boolean;
  default_namespace: string;
  health_status: ClusterHealthStatus;
  health_reason: string | null;
  health_checked_at: string | null;
  config_version: number;
  updated_at: string | null;
  updated_by_user_id: number | null;
};

export type ClusterConfigScopeEntry = {
  scope_type: ClusterScopeType;
  tenant_id: string | null;
  using_platform_default: boolean;
  config: ClusterConfigRead | null;
};

export type ClusterConfigScopeList = { items: ClusterConfigScopeEntry[] };

export type ConnectionTestResult = {
  status: ClusterHealthStatus;
  reason: string | null;
  server_version: string | null;
  platform: string | null;
  namespace_count: number | null;
  node_count: number | null;
  api_url: string | null;
};

export type ClusterConfigUpsertPayload = {
  mode: ClusterMode;
  api_url?: string | null;
  token?: string | null; // write-only
  verify_ssl: boolean;
  default_namespace: string;
};

// Scope path token: "platform-default" or "tenant:{id}".
export const PLATFORM_DEFAULT_SCOPE = "platform-default";
export function tenantScope(tenantId: string): string {
  return `tenant:${tenantId}`;
}

export async function listScopes(): Promise<ClusterConfigScopeList> {
  const res = await api.get<ClusterConfigScopeList>("/infrastructure/scopes");
  return res.data;
}

export async function getScope(scope: string): Promise<ClusterConfigScopeEntry> {
  const res = await api.get<ClusterConfigScopeEntry>(
    `/infrastructure/${encodeURIComponent(scope)}`,
  );
  return res.data;
}

export async function upsertScope(
  scope: string,
  payload: ClusterConfigUpsertPayload,
): Promise<ClusterConfigRead> {
  const res = await api.put<ClusterConfigRead>(
    `/infrastructure/${encodeURIComponent(scope)}`,
    payload,
  );
  return res.data;
}

export async function uploadKubeconfig(
  scope: string,
  file: File,
): Promise<ClusterConfigRead> {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post<ClusterConfigRead>(
    `/infrastructure/${encodeURIComponent(scope)}/kubeconfig`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}

export async function testConnection(
  scope: string,
): Promise<ConnectionTestResult> {
  const res = await api.post<ConnectionTestResult>(
    `/infrastructure/${encodeURIComponent(scope)}/test`,
  );
  return res.data;
}

export async function deleteScope(scope: string): Promise<void> {
  await api.delete(`/infrastructure/${encodeURIComponent(scope)}`);
}
