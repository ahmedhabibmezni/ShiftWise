import { useMemo } from "react";
import { Lock, ShieldCheck } from "lucide-react";
import { ALL_ACTIONS, ROLE_ACTIONS, type RoleAction } from "@/api/roles";
import type { RolePermissions } from "@/api/roles";
import { Icon } from "./Icon";
import { cn } from "@/lib/cn";

/**
 * Permission matrix — resources × actions, with a "*" (wildcard) column that
 * collapses to the single-element list `["*"]` when sent to the API. When the
 * row is in wildcard mode, the four action columns are locked and rendered
 * as implicitly-true (the operator must turn `*` off to set actions manually).
 *
 * The same component renders in read-only mode (no `onChange`) so we can
 * reuse it in both the detail view and the create/edit forms.
 */
export function PermissionsMatrix({
  resources,
  permissions,
  onChange,
  disabled,
  describeResource,
}: {
  resources: string[];
  permissions: RolePermissions;
  onChange?: (next: RolePermissions) => void;
  disabled?: boolean;
  describeResource?: (resource: string) => string | undefined;
}) {
  const readOnly = !onChange || disabled;

  const rows = useMemo(
    () => resources.slice().sort((a, b) => a.localeCompare(b)),
    [resources],
  );

  const setCell = (resource: string, column: RoleAction | "wildcard", checked: boolean) => {
    if (readOnly) return;
    const list = permissions[resource] ?? [];
    let nextList: string[];

    if (column === "wildcard") {
      nextList = checked ? [ALL_ACTIONS] : [];
    } else {
      const filtered = list.filter((a) => a !== ALL_ACTIONS && a !== column);
      nextList = checked ? [...filtered, column] : filtered;
    }

    const next: RolePermissions = { ...permissions };
    if (nextList.length === 0) {
      delete next[resource];
    } else {
      next[resource] = nextList;
    }
    onChange!(next);
  };

  return (
    <div className="border border-line bg-bg-elev overflow-hidden">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-line bg-bg-elev-2">
            <th className="text-left px-3 py-2 kicker">resource</th>
            {ROLE_ACTIONS.map((a) => (
              <th key={a} className="text-center px-2 py-2 kicker w-16">
                {a}
              </th>
            ))}
            <th
              className="text-center px-2 py-2 kicker w-16"
              title="grant all actions on this resource"
            >
              all
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((resource) => {
            const list = permissions[resource] ?? [];
            const wild = list.includes(ALL_ACTIONS);
            const hint = describeResource?.(resource);
            return (
              <tr key={resource} className="border-b border-line/50 last:border-b-0">
                <td className="px-3 py-2 align-middle">
                  <div className="font-mono text-[12px] text-ink">{resource}</div>
                  {hint && (
                    <div className="font-mono text-[10px] text-ink-muted lowercase mt-0.5">
                      {hint}
                    </div>
                  )}
                </td>
                {ROLE_ACTIONS.map((action) => {
                  const granted = wild || list.includes(action);
                  return (
                    <td key={action} className="text-center px-2 py-2 align-middle">
                      <Cell
                        checked={granted}
                        disabled={readOnly || wild}
                        wildLocked={wild && !readOnly}
                        onChange={(c) => setCell(resource, action, c)}
                        label={`${action} ${resource}`}
                      />
                    </td>
                  );
                })}
                <td className="text-center px-2 py-2 align-middle">
                  <Cell
                    checked={wild}
                    disabled={readOnly}
                    onChange={(c) => setCell(resource, "wildcard", c)}
                    label={`wildcard on ${resource}`}
                    accent
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Cell({
  checked,
  disabled,
  wildLocked,
  onChange,
  label,
  accent,
}: {
  checked: boolean;
  disabled?: boolean;
  wildLocked?: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  accent?: boolean;
}) {
  return (
    <label
      className={cn(
        "relative inline-flex items-center justify-center h-6 w-6 cursor-pointer",
        "border transition-colors duration-150",
        disabled && "cursor-not-allowed",
        checked
          ? accent
            ? "bg-signal/15 border-signal text-signal"
            : "bg-ok/15 border-ok text-ok"
          : "bg-bg-elev-2 border-line text-ink-faint",
      )}
      title={label}
    >
      <input
        type="checkbox"
        aria-label={label}
        className="sr-only"
        checked={checked}
        disabled={disabled && !wildLocked}
        onChange={(e) => onChange(e.target.checked)}
        readOnly={disabled}
      />
      {checked ? (
        accent ? (
          <Icon icon={ShieldCheck} size={12} />
        ) : (
          <span aria-hidden className="font-mono text-[12px]">
            ✓
          </span>
        )
      ) : wildLocked ? (
        <Icon icon={Lock} size={10} />
      ) : null}
    </label>
  );
}
