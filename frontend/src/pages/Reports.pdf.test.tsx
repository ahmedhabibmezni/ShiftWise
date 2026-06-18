import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/axios";
import { downloadReportsPdf } from "@/api/migrations";

// These tests mock the axios instance directly rather than routing through
// MSW + a real XMLHttpRequest blob round-trip. Under jsdom the
// `responseType: "blob"` XHR path does not reliably resolve in CI (the awaited
// request hangs to the test timeout), even though it passes locally. Mocking
// `api.get` exercises all of downloadReportsPdf's own logic — filename parsing,
// object-URL creation, the anchor click, and revocation — deterministically in
// any environment.
describe("downloadReportsPdf", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests the PDF as a blob and triggers a browser download", async () => {
    const blob = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46])], {
      type: "application/pdf",
    });
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({
      data: blob,
      headers: {
        "content-disposition":
          'attachment; filename="shiftwise-report-cluster-20260521.pdf"',
      },
    });

    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:test");
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockReturnValue(undefined as unknown as void);

    // Capture the anchor click so we don't navigate away in jsdom, and assert
    // the parsed filename lands on the download attribute.
    const clickSpy = vi.fn();
    let anchor: HTMLAnchorElement | undefined;
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreateElement(tag);
      if (tag === "a") {
        anchor = el as HTMLAnchorElement;
        anchor.click = clickSpy;
      }
      return el;
    });

    await downloadReportsPdf();

    expect(getSpy).toHaveBeenCalledWith("/reports/export/pdf", {
      responseType: "blob",
    });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(anchor?.download).toBe("shiftwise-report-cluster-20260521.pdf");
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("surfaces an error when the endpoint refuses with 413", async () => {
    vi.spyOn(api, "get").mockRejectedValue(
      new Error("Request failed with status code 413"),
    );

    await expect(downloadReportsPdf()).rejects.toBeDefined();
  });
});
