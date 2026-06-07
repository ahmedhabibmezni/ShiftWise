import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { ServerCog, Upload, Trash2, Activity } from "lucide-react";

import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import type { BadgeVariant } from "@/components/ui/Badge";
import { describeError } from "@/lib/errors";
import { useAuthStore } from "@/store/auth";
import {
  CLUSTER_MODES,
  PLATFORM_DEFAULT_SCOPE,
  type ClusterConfigRead,
  type ClusterHealthStatus,
  type ClusterMode,
  type ConnectionTestResult,
  deleteScope,
  getScope,
  listScopes,
  tenantScope,
  testConnection,
  uploadKubeconfig,
  upsertScope,
} from "@/api/infrastructure";

const HEALTH_TONE: Record<ClusterHealthStatus, BadgeVariant> = {
  healthy: "ok",
  degraded: "warn",
  unreachable: "critical",
  auth_failed: "critical",
  invalid: "critical",
  unknown: "neutral",
};

/**
 * Infrastructure — superadmin / tenant-admin cluster connectivity management.
 *
 * A superadmin selects a scope (platform-default or a tenant); a tenant admin
 * is locked to their own tenant. The form adapts to the chosen connection mode
 * (kubeconfig upload / in-cluster info / custom URL+token). in-cluster is only
 * offered for the platform-default scope.
 */
export default function Infrastructure() {
  const user = useAuthStore((s) => s.user);
  const isSuperuser = Boolean(user?.is_superuser);
  const tenantId = user?.tenant_id ?? "";

  // Available scopes the user can target.
  const scopesQuery = useQuery({
    queryKey: ["infra", "scopes"],
    queryFn: listScopes,
  });

  const ownTenantScopeToken = tenantId ? tenantScope(tenantId) : "";
  const [selectedScope, setSelectedScope] = useState<string>(
    isSuperuser ? PLATFORM_DEFAULT_SCOPE : ownTenantScopeToken,
  );

  const scopeOptions = useMemo(() => {
    if (!isSuperuser) {
      return ownTenantScopeToken
        ? [{ value: ownTenantScopeToken, label: `Tenant: ${tenantId}` }]
        : [];
    }
    const opts = [{ value: PLATFORM_DEFAULT_SCOPE, label: "Platform default" }];
    for (const entry of scopesQuery.data?.items ?? []) {
      if (entry.scope_type === "tenant" && entry.tenant_id) {
        opts.push({
          value: tenantScope(entry.tenant_id),
          label: `Tenant: ${entry.tenant_id}`,
        });
      }
    }
    return opts;
  }, [isSuperuser, ownTenantScopeToken, tenantId, scopesQuery.data]);

  const isPlatformDefault = selectedScope === PLATFORM_DEFAULT_SCOPE;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Infrastructure" />

      {scopeOptions.length > 1 && (
        <div className="flex items-center gap-3">
          <label className="text-[13px] font-semibold text-[var(--text-secondary)]">
            Scope
          </label>
          <Select
            value={selectedScope}
            onChange={(e) => setSelectedScope(e.target.value)}
            className="max-w-xs"
          >
            {scopeOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </div>
      )}

      {selectedScope ? (
        <ScopeEditor scope={selectedScope} isPlatformDefault={isPlatformDefault} />
      ) : (
        <Panel>
          <p className="text-[13px] text-[var(--text-secondary)]">
            No tenant is associated with your account.
          </p>
        </Panel>
      )}
    </div>
  );
}

function HealthBadge({ status, reason }: { status: ClusterHealthStatus; reason: string | null }) {
  return (
    <div className="flex items-center gap-2">
      <Badge variant={HEALTH_TONE[status]}>{status.replace("_", " ")}</Badge>
      {/* {reason && (
        <span className="text-[12px] text-[var(--text-muted)] truncate max-w-[48ch]">
          {reason}
        </span>
      )} */}
    </div>
  );
}

function ScopeEditor({
  scope,
  isPlatformDefault,
}: {
  scope: string;
  isPlatformDefault: boolean;
}) {
  const scopeQuery = useQuery({
    queryKey: ["infra", "scope", scope],
    queryFn: () => getScope(scope),
  });

  if (scopeQuery.isLoading) {
    return (
      <Panel>
        <p className="text-[13px] text-[var(--text-secondary)]">Loading…</p>
      </Panel>
    );
  }

  const config = scopeQuery.data?.config ?? null;
  const usingDefault = scopeQuery.data?.using_platform_default ?? false;

  // Remount the editor when the loaded config changes so local form state
  // seeds correctly from the resolved values (useState initialisers run once).
  return (
    <ScopeEditorInner
      key={`${scope}:${config?.config_version ?? "none"}`}
      scope={scope}
      isPlatformDefault={isPlatformDefault}
      config={config}
      usingDefault={usingDefault}
    />
  );
}

function ScopeEditorInner({
  scope,
  isPlatformDefault,
  config,
  usingDefault,
}: {
  scope: string;
  isPlatformDefault: boolean;
  config: ClusterConfigRead | null;
  usingDefault: boolean;
}) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<ClusterMode>(config?.mode ?? "kubeconfig");
  const [apiUrl, setApiUrl] = useState(config?.api_url ?? "");
  const [token, setToken] = useState("");
  const [verifySsl, setVerifySsl] = useState(config?.verify_ssl ?? false);
  const [namespace, setNamespace] = useState(config?.default_namespace ?? "default");

  // Modes available for this scope: in-cluster only for the platform default.
  const availableModes = isPlatformDefault
    ? CLUSTER_MODES
    : CLUSTER_MODES.filter((m) => m !== "incluster");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["infra"] });
  };

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadKubeconfig(scope, file),
    onSuccess: () => {
      toast.success("Kubeconfig applied");
      invalidate();
    },
    onError: (err) => toast.error(describeError(err, "Upload failed")),
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      upsertScope(scope, {
        mode,
        api_url: mode === "custom" ? apiUrl : null,
        token: mode === "custom" && token ? token : null,
        verify_ssl: verifySsl,
        default_namespace: namespace,
      }),
    onSuccess: () => {
      toast.success("Configuration saved");
      setToken("");
      invalidate();
    },
    onError: (err) => toast.error(describeError(err, "Save failed")),
  });

  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  const testMutation = useMutation<ConnectionTestResult>({
    mutationFn: () => testConnection(scope),
    onSuccess: (res) => {
      setTestResult(res);
      if (res.status === "healthy") toast.success("Cluster reachable");
      else toast.error(res.reason ?? `Connection ${res.status}`);
      invalidate();
    },
    onError: (err) => {
      setTestResult(null);
      toast.error(describeError(err, "Test failed"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteScope(scope),
    onSuccess: () => {
      toast.success("Override cleared — reverted to platform default");
      invalidate();
    },
    onError: (err) => toast.error(describeError(err, "Delete failed")),
  });

  return (
    <div className="flex flex-col gap-5">
      {/* Status panel */}
      <Panel>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <ServerCog size={18} className="text-[var(--accent-light)]" />
            <div className="flex flex-col">
              <span className="text-[14px] font-semibold text-[var(--text-primary)]">
                {isPlatformDefault ? "Platform default" : scope}
              </span>
              <span className="text-[12px] text-[var(--text-muted)]">
                {usingDefault
                  ? "Using platform default (no override set)"
                  : config
                    ? `Mode: ${config.mode} · v${config.config_version}`
                    : "Not yet configured"}
              </span>
            </div>
          </div>
          {config && (
            <HealthBadge status={config.health_status} reason={config.health_reason} />
          )}
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={<Activity size={14} />}
            loading={testMutation.isPending}
            onClick={() => testMutation.mutate()}
          >
            Test connection
          </Button>
        </div>
      </Panel>

      {/* Live cluster details — shown after a successful reachability probe. */}
      {testResult?.status === "healthy" && (
        <ClusterDetails result={testResult} />
      )}

      {/* Mode + adaptive form */}
      <Panel>
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <label className="text-[13px] font-semibold text-[var(--text-secondary)] w-32">
              Connection mode
            </label>
            <Select
              value={mode}
              onChange={(e) => setMode(e.target.value as ClusterMode)}
              className="max-w-xs"
            >
              {availableModes.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </div>

          {mode === "kubeconfig" && (
            <div className="flex flex-col gap-2">
              <p className="text-[12px] text-[var(--text-muted)]">
                Upload a kubeconfig file. It is validated and stored encrypted —
                it never touches the server filesystem.
              </p>
              <input
                ref={fileRef}
                type="file"
                accept=".yaml,.yml,.config,.kubeconfig,text/plain,application/yaml"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadMutation.mutate(f);
                  e.target.value = "";
                }}
              />
              <Button
                variant="primary"
                size="sm"
                leadingIcon={<Upload size={14} />}
                loading={uploadMutation.isPending}
                onClick={() => fileRef.current?.click()}
                className="self-start"
              >
                Upload kubeconfig
              </Button>
            </div>
          )}

          {mode === "incluster" && (
            <p className="text-[13px] text-[var(--text-secondary)]">
              ShiftWise will use its own in-cluster service account. No credentials
              are required. Available only when running inside a cluster.
            </p>
          )}

          {mode === "custom" && (
            <div className="flex flex-col gap-3 max-w-xl">
              <Field label="API server URL">
                <Input
                  placeholder="https://api.cluster.example.com:6443"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                />
              </Field>
              <Field label="Bearer token">
                <Input
                  type="password"
                  placeholder={config?.has_credentials ? "•••••••• (unchanged)" : "Paste token"}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              </Field>
              <label className="flex items-center gap-2 text-[13px] text-[var(--text-secondary)]">
                <input
                  type="checkbox"
                  checked={verifySsl}
                  onChange={(e) => setVerifySsl(e.target.checked)}
                />
                Verify TLS certificate
              </label>
            </div>
          )}

          {mode !== "incluster" && (
            <Field label="Default namespace">
              <Input
                className="max-w-xs"
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
              />
            </Field>
          )}

          {mode !== "kubeconfig" && (
            <Button
              variant="primary"
              size="sm"
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
              className="self-start"
            >
              Save configuration
            </Button>
          )}
        </div>
      </Panel>

      {/* Revert (tenant scopes only) */}
      {!isPlatformDefault && config && (
        <Panel>
          <div className="flex items-center justify-between gap-4">
            <span className="text-[13px] text-[var(--text-secondary)]">
              Clear this tenant override and revert to the platform default cluster.
            </span>
            <Button
              variant="danger"
              size="sm"
              leadingIcon={<Trash2 size={14} />}
              loading={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              Clear override
            </Button>
          </div>
        </Panel>
      )}
    </div>
  );
}

function ClusterDetails({ result }: { result: ConnectionTestResult }) {
  // Only render rows whose detail is present (a restricted RBAC may leave
  // node_count / version null without changing the healthy verdict).
  const rows: Array<{ label: string; value: string }> = [];
  if (result.api_url) rows.push({ label: "API server", value: result.api_url });
  if (result.server_version)
    rows.push({ label: "Kubernetes version", value: result.server_version });
  if (result.platform) rows.push({ label: "Platform", value: result.platform });
  if (result.namespace_count != null)
    rows.push({ label: "Namespaces", value: String(result.namespace_count) });
  if (result.node_count != null)
    rows.push({ label: "Nodes", value: String(result.node_count) });

  return (
    <Panel>
      <div className="flex items-center gap-2 mb-3">
        <Activity size={15} className="text-[var(--accent-light)]" />
        <span className="text-[13px] font-semibold text-[var(--text-primary)]">
          Cluster details
        </span>
        <Badge variant="ok">reachable</Badge>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2.5">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between gap-4 min-w-0">
            <dt className="text-[12px] text-[var(--text-muted)] shrink-0">{r.label}</dt>
            <dd className="text-[13px] font-medium text-[var(--text-primary)] truncate text-right">
              {r.value}
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[13px] font-semibold text-[var(--text-secondary)]">
        {label}
      </label>
      {children}
    </div>
  );
}
