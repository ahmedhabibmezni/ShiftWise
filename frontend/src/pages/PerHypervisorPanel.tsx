import { Server } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { formatNumber } from "@/lib/format";
import type { MigrationStatsByGroup } from "@/api/stats";

/**
 * Per-hypervisor migration outcome breakdown (US2).
 *
 * Visible to any caller with `reports:read`. Rows are scoped to the
 * caller's tenant by the backend; superusers see every hypervisor in
 * the cluster.
 */
export function PerHypervisorPanel({
  rows,
}: {
  rows: MigrationStatsByGroup[];
}) {
  return (
    <Panel
      icon={Server}
      iconTone="accent"
      kicker={`${rows.length} hypervisor${rows.length === 1 ? "" : "s"}`}
      title="Outcomes by Hypervisor"
      bodyClassName="px-0"
    >
      {rows.length === 0 ? (
        <EmptyState
          icon={Server}
          title="No hypervisor data yet"
          hint="Migrations will appear here grouped by their source hypervisor."
        />
      ) : (
        <Table className="px-2" data-testid="per-hypervisor-table" aria-label="Migrations by hypervisor">
          <THead>
            <TR>
              <TH>Hypervisor</TH>
              <TH numeric>Completed</TH>
              <TH numeric>Failed</TH>
              <TH numeric>Total</TH>
            </TR>
          </THead>
          <tbody>
            {rows.map((row) => (
              <TR key={row.key} data-testid="per-hypervisor-row">
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
      )}
    </Panel>
  );
}
