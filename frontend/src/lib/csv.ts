/**
 * Minimal client-side CSV writer + browser download trigger.
 *
 * Why hand-rolled instead of a library: the dataset is small (paged
 * migration list, max a few hundred rows) and the escaping rules are
 * tame — RFC 4180 with CRLF separators and double-quote escaping. A
 * dependency for this would be 10x bigger than the implementation.
 */

export type CsvColumn<T> = {
  /** Header label written to the first row. */
  header: string;
  /** Extractor — receives the row, returns a string-coerceable value. */
  value: (row: T) => string | number | boolean | null | undefined;
};

// Leading characters that a spreadsheet (Excel, Google Sheets, LibreOffice)
// treats as the start of a formula. A crafted cell such as
// `=HYPERLINK("http://evil")` or `=cmd|'/c calc'!A1` would execute on open —
// CSV injection. Tab and CR are included because Excel strips them and then
// re-evaluates the remainder.
const FORMULA_TRIGGERS = new Set(["=", "+", "-", "@", "\t", "\r"]);

function escapeCell(
  raw: string | number | boolean | null | undefined,
): string {
  if (raw === null || raw === undefined) return "";
  let s = String(raw);
  // Formula-injection neutralisation: prefix a single quote so the cell is
  // forced to text. Done before RFC-4180 quoting so the quote ends up inside
  // the double-quotes when the cell also needs quoting.
  if (s.length > 0 && FORMULA_TRIGGERS.has(s[0])) {
    s = `'${s}`;
  }
  // RFC 4180: a field containing a comma, double-quote or line-break must
  // be wrapped in double quotes; any embedded double-quote is doubled.
  if (/[",\r\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function rowsToCsv<T>(rows: readonly T[], columns: readonly CsvColumn<T>[]): string {
  const head = columns.map((c) => escapeCell(c.header)).join(",");
  const body = rows
    .map((row) => columns.map((c) => escapeCell(c.value(row))).join(","))
    .join("\r\n");
  // Single trailing CRLF so spreadsheet apps recognise the final row.
  return body.length > 0 ? `${head}\r\n${body}\r\n` : `${head}\r\n`;
}

/**
 * Trigger a browser download with the given CSV payload. Uses a temporary
 * anchor + object URL — no library, no server round-trip.
 */
export function downloadCsv(filename: string, content: string): void {
  // BOM so Excel auto-detects UTF-8 instead of mojibake-ing accented chars.
  const blob = new Blob(["﻿" + content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Defer revoke so the click handler has a chance to read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
