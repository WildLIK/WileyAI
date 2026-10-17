import test from "node:test";
import assert from "node:assert/strict";
import { documentCoverage } from "../../src/documentCoverage.ts";

test("document coverage counts Unicode characters and overlaps once per document", () => {
  const part = {
    document_id: "first",
    name: "Книга.txt",
    offset: 0,
    text: "А😺БВ",
    total: 10,
  };
  assert.deepEqual(
    documentCoverage([part, { ...part, offset: 2, text: "БВГ" }]),
    [{ name: "Книга.txt", covered: 5, total: 10, partial: true }],
  );
  assert.deepEqual(documentCoverage([{ ...part, total: 4 }]), [
    { name: "Книга.txt", covered: 4, total: 4, partial: false },
  ]);
});
