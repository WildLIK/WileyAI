function normalized(text: string) {
  return text
    .toLocaleLowerCase("ru-RU")
    .replace(/ё/g, "е")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/** Explicit activation at the beginning, not an incidental mention in a sentence. */
export function activated(
  text: string,
  word: string,
  required = true,
): string | null {
  if (!required) return text.trim();
  const name = normalized(word);
  const value = normalized(text);
  if (!name || !value.startsWith(name + " ")) return null;
  // Keep the original language/case of song names and punctuation after the name.
  const tokens = [...text.trim().matchAll(/[\p{L}\p{N}]+/gu)];
  const count = name.split(" ").length;
  if (!tokens[count - 1] || tokens[0].index !== 0) return null;
  const last = tokens[count - 1];
  const command = text
    .trim()
    .slice(last.index! + last[0].length)
    .replace(/^[,.:;!—\s]+/u, "")
    .trim();
  return command || null;
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
