import type { DocumentFragment } from "./api";

export function documentCoverage(sources: DocumentFragment[]) {
  const docs = new Map<
    string,
    { name: string; total: number; ranges: [number, number][] }
  >();
  for (const source of sources) {
    const item = docs.get(source.document_id) || {
      name: source.name,
      total: source.total,
      ranges: [],
    };
    item.ranges.push([source.offset, source.offset + [...source.text].length]);
    docs.set(source.document_id, item);
  }
  return [...docs.values()].map((item) => {
    let end = 0,
      covered = 0;
    for (const [start, stop] of item.ranges.sort((a, b) => a[0] - b[0])) {
      covered += Math.max(0, stop - Math.max(end, start));
      end = Math.max(end, stop);
    }
    return {
      name: item.name,
      total: item.total,
      covered,
      partial: covered < item.total,
    };
  });
}
