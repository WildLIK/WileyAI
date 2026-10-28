function normalized(text: string) {
  return text
    .toLocaleLowerCase("ru-RU")
    .replace(/ё/g, "е")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/** Short interjections said before the name: «Эй, Уайли», «Слушай, Уайли». */
const FILLERS = new Set(["эй", "ну", "так", "слушай", "окей", "алло", "хей"]);
const LATIN: Record<string, string> = {
  a: "а",
  b: "б",
  c: "к",
  d: "д",
  e: "е",
  f: "ф",
  g: "г",
  h: "х",
  i: "и",
  j: "дж",
  k: "к",
  l: "л",
  m: "м",
  n: "н",
  o: "о",
  p: "п",
  q: "к",
  r: "р",
  s: "с",
  t: "т",
  u: "у",
  v: "в",
  w: "у",
  x: "кс",
  y: "й",
  z: "з",
};

/** Whisper writes the name in Latin at times («Wiley»); compare by sound. */
function cyrillic(word: string) {
  return word
    .replace(/^wh?[iy]/, "уай")
    .replace(/^wh?/, "у")
    .replace(/(?:ley|lie|lee|ly)$/, "ли")
    .replace(/[a-z]/g, (letter) => LATIN[letter]);
}

function distance(a: string, b: string) {
  let row = Array.from({ length: b.length + 1 }, (_, index) => index);
  for (let i = 1; i <= a.length; i++) {
    const next = [i];
    for (let j = 1; j <= b.length; j++)
      next[j] = Math.min(
        row[j] + 1,
        next[j - 1] + 1,
        row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    row = next;
  }
  return row[b.length];
}

/** Recognition often swaps one or two sounds of a rare name («Майли», «Уали», «Wiley»). */
function sounds(heard: string, name: string) {
  if (heard === name) return true;
  const value = cyrillic(heard);
  const allowed = name.length >= 7 ? 2 : name.length >= 4 ? 1 : 0;
  return (
    distance(value, name) <= allowed ||
    // Two edits only when the ending is kept: «вейли», «уэйли», but not «ладно».
    (name.length >= 5 &&
      value.length === name.length &&
      distance(value, name) <= 2 &&
      value.slice(-2) === name.slice(-2))
  );
}

/**
 * Locate the spoken name at the very beginning (after at most one filler).
 * Returns the source index just after it, or null for no explicit address.
 */
function addressEnd(text: string, word: string): number | null {
  const name = normalized(word).split(" ");
  if (!name[0]) return null;
  const tokens = [...text.trim().matchAll(/[\p{L}\p{N}]+/gu)];
  if (!tokens.length || tokens[0].index !== 0) return null;
  const lower = tokens.map((token) =>
    token[0].toLocaleLowerCase("ru-RU").replace(/ё/g, "е"),
  );
  for (const skip of FILLERS.has(lower[0]) ? [0, 1] : [0]) {
    const heard = lower.slice(skip, skip + name.length);
    if (heard.length !== name.length) continue;
    const exact = heard.join(" ") === name.join(" ");
    if (exact || sounds(heard.join(""), name.join(""))) {
      const last = tokens[skip + name.length - 1];
      return last.index! + last[0].length;
    }
  }
  return null;
}

/** Explicit activation at the beginning, not an incidental mention in a sentence. */
export function activated(
  text: string,
  word: string,
  required = true,
): string | null {
  const value = text.trim();
  const end = addressEnd(value, word);
  if (end === null) return required ? null : value;
  // Keep the original language/case of song names and punctuation after the name.
  const command = value
    .slice(end)
    .replace(/^[,.:;!?—\s]+/u, "")
    .trim();
  if (required) return command || null;
  // The address, even misheard («Майли, пауза»), is not part of the command.
  return command || value;
}

/** Reject recognized playback, including partial/asr-normalized copies. */
export function playbackEcho(heard: string, playback: string): boolean {
  const value = normalized(heard),
    source = normalized(playback);
  if (!value || !source) return false;
  if (source.includes(value)) return true;
  const tokens = value.split(" ").filter((word) => word.length > 2);
  const original = new Set(source.split(" "));
  return (
    tokens.length >= 3 &&
    tokens.filter((word) => original.has(word)).length / tokens.length >= 0.8
  );
}
