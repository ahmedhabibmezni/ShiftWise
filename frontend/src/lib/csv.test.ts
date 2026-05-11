import { describe, expect, it } from "vitest";
import { rowsToCsv, type CsvColumn } from "./csv";

describe("rowsToCsv", () => {
  type Row = { id: number; name: string; note: string | null };

  const columns: CsvColumn<Row>[] = [
    { header: "id", value: (r) => r.id },
    { header: "name", value: (r) => r.name },
    { header: "note", value: (r) => r.note },
  ];

  it("writes a header row even when there are no data rows", () => {
    const out = rowsToCsv<Row>([], columns);
    expect(out).toBe("id,name,note\r\n");
  });

  it("CRLF-separates rows and trails with a CRLF", () => {
    const out = rowsToCsv<Row>(
      [
        { id: 1, name: "alpha", note: "ok" },
        { id: 2, name: "beta", note: "ok" },
      ],
      columns,
    );
    expect(out).toBe("id,name,note\r\n1,alpha,ok\r\n2,beta,ok\r\n");
  });

  it("quotes cells containing commas, double-quotes or newlines", () => {
    const out = rowsToCsv<Row>(
      [
        { id: 1, name: "a, b", note: 'he said "hi"' },
        { id: 2, name: "line\nbreak", note: null },
      ],
      columns,
    );
    expect(out).toBe(
      'id,name,note\r\n1,"a, b","he said ""hi"""\r\n2,"line\nbreak",\r\n',
    );
  });

  it("renders nullish values as empty cells", () => {
    const out = rowsToCsv<Row>([{ id: 1, name: "x", note: null }], columns);
    expect(out).toBe("id,name,note\r\n1,x,\r\n");
  });
});
