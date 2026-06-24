import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PerTenantPanel } from "@/pages/PerTenantPanel";

describe("PerTenantPanel", () => {
  it("renders one row per tenant when the backend returns populated data", () => {
    render(
      <PerTenantPanel
        rows={[
          {
            key: "tenant-a",
            label: "tenant-a",
            total: 7,
            completed: 6,
            failed: 1,
          },
          {
            key: "tenant-b",
            label: "tenant-b",
            total: 3,
            completed: 3,
            failed: 0,
          },
        ]}
      />,
    );

    const rows = screen.getAllByTestId("per-tenant-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("tenant-a");
    expect(rows[1]).toHaveTextContent("tenant-b");
  });

  it("renders nothing when by_tenant is empty (non-superuser path)", () => {
    const { container } = render(<PerTenantPanel rows={[]} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("per-tenant-table")).not.toBeInTheDocument();
  });
});
