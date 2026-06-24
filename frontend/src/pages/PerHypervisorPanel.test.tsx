import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PerHypervisorPanel } from "@/pages/PerHypervisorPanel";

describe("PerHypervisorPanel", () => {
  it("renders one row per hypervisor in the order supplied by the backend", () => {
    render(
      <PerHypervisorPanel
        rows={[
          {
            key: "1",
            label: "vsphere-prod-1",
            total: 12,
            completed: 10,
            failed: 2,
          },
          {
            key: "2",
            label: "kvm-edge-1",
            total: 5,
            completed: 5,
            failed: 0,
          },
        ]}
      />,
    );

    const rows = screen.getAllByTestId("per-hypervisor-row");
    expect(rows).toHaveLength(2);

    expect(rows[0]).toHaveTextContent("vsphere-prod-1");
    expect(rows[0]).toHaveTextContent("10");
    expect(rows[0]).toHaveTextContent("12");

    expect(rows[1]).toHaveTextContent("kvm-edge-1");
    expect(rows[1]).toHaveTextContent("5");
  });

  it("renders the empty state without crashing on zero rows", () => {
    render(<PerHypervisorPanel rows={[]} />);

    expect(screen.queryByTestId("per-hypervisor-table")).not.toBeInTheDocument();
    expect(screen.getByText(/no hypervisor data yet/i)).toBeInTheDocument();
  });
});
