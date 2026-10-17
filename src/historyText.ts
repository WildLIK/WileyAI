export function historyParts(
  text: string,
  terms: string[],
  limit = 80,
): { text: string; match: boolean }[] {
  const safe = terms
    .slice(0, 12)
    .filter((term) => /^[\p{L}\p{N}]{1,200}$/u.test(term));
  if (!safe.length) return [{ text, match: false }];
  const expression = new RegExp(
    "(?<![\\p{L}\\p{N}])(" +
      safe.map((term) => term.replace(/е/giu, "[её]")).join("|") +
      ")[\\p{L}\\p{N}\\p{M}]*",
    "giu",
  );
  const parts = [];
  let offset = 0,
    count = 0,
    found: RegExpExecArray | null;
  while (count < limit && (found = expression.exec(text))) {
    if (found.index > offset)
      parts.push({ text: text.slice(offset, found.index), match: false });
    parts.push({ text: found[0], match: true });
    offset = found.index + found[0].length;
    count++;
  }
  if (offset < text.length)
    parts.push({ text: text.slice(offset), match: false });
  return parts;
}
