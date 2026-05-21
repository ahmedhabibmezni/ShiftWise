import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/msw/server";
import { downloadReportsPdf } from "@/api/migrations";

describe("downloadReportsPdf", () => {
  it("requests the PDF as a blob and triggers a browser download", async () => {
    const pdfBytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31]); // %PDF-1
    server.use(
      http.get("*/api/v1/reports/export/pdf", () =>
        HttpResponse.arrayBuffer(pdfBytes.buffer, {
          headers: {
            "Content-Type": "application/pdf",
            "Content-Disposition":
              'attachment; filename="shiftwise-report-cluster-20260521.pdf"',
          },
        }),
      ),
    );

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test");
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockReturnValue(undefined as unknown as void);

    // Capture the anchor click so we don't navigate away in jsdom.
    const clickSpy = vi.fn();
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreateElement(tag);
      if (tag === "a") {
        (el as HTMLAnchorElement).click = clickSpy;
      }
      return el;
    });

    await downloadReportsPdf();

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("surfaces an error when the endpoint refuses with 413", async () => {
    server.use(
      http.get("*/api/v1/reports/export/pdf", () =>
        HttpResponse.json(
          { detail: "Scope too large for synchronous export. Filter by date range." },
          { status: 413 },
        ),
      ),
    );

    await expect(downloadReportsPdf()).rejects.toBeDefined();
  });
});
