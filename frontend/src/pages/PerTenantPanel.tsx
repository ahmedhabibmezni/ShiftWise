import { Building2 } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { formatNumber } from "@/lib/format";
import type { MigrationStatsByGroup } from "@/api/stats";

/**
 * Per-tenant migration outcome breakdown (US2).
 *
 * Visible only when the backend's `by_tenant` field is non-empty — i.e.,
 * the caller is a superuser. The frontend NEVER decides visibility on
 * its own; the backend RBAC layer (see crud/migration.py and the
 * `/migrations/stats/summary` handler) returns `by_tenant: []` for any
 * non-privileged caller and a populated list for superusers. Render the
 * panel iff `rows.length > 0` so a tenant user does not see a stub
 * "No data" card.
 */
export function PerTenantPanel({
  rows,
}: {
  rows: MigrationStatsByGroup[];
}) {
  if (rows.length === 0) {
    return null;
  }
  return (
    <Panel
      icon={Building2}
      iconTone="accent"
      kicker={`${rows.length} tenant${rows.length === 1 ? "" : "s"}`}
      title="Outcomes by Tenant"
      bodyClassName="px-0"
    >
      <Table className="px-2" data-testid="per-tenant-table">
        <THead>
          <TR>
            <TH>Tenant</TH>
            <TH numeric>Completed</TH>
            <TH numeric>Failed</TH>
            <TH numeric>Total</TH>
          </TR>
        </THead>
        <tbody>
          {rows.map((row) => (
            <TR key={row.key} data-testid="per-tenant-row">
              <TD>{row.label}</TD>
              <TD numeric>{formatNumber(row.completed)}</TD>
              <TD numeric muted={row.failed === 0}>
                {formatNumber(row.failed)}
              </TD>
              <TD numeric muted>{formatNumber(row.total)}</TD>
            </TR>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}
