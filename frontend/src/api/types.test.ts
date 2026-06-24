import { describe, expect, it } from "vitest";
import { totalPages } from "./types";

// F26 — the list endpoints return an inconsistent pagination envelope:
// `/users` sends a precomputed `pages`, the others do not. `totalPages()`
// is the single derivation point so every page renders the same count.
describe("totalPages — unified page-count derivation", () => {
  it("uses the backend-supplied `pages` when present and positive", () => {
    expect(totalPages({ total: 51, page_size: 25, pages: 3 })).toBe(3);
  });

  it("computes the count from total / page_size when `pages` is absent", () => {
    expect(totalPages({ total: 51, page_size: 25 })).toBe(3);
    expect(totalPages({ total: 50, page_size: 25 })).toBe(2);
    expect(totalPages({ total: 25, page_size: 25 })).toBe(1);
  });

  it("returns at least 1 for an empty list", () => {
    expect(totalPages({ total: 0, page_size: 25 })).toBe(1);
    expect(totalPages({ total: 0, page_size: 25, pages: 0 })).toBe(1);
  });

  it("does not divide by a zero or negative page_size", () => {
    expect(totalPages({ total: 100, page_size: 0 })).toBe(1);
    expect(totalPages({ total: 100, page_size: -5 })).toBe(1);
  });
});
