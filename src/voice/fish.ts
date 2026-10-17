export const MITA_VOICE = "ff1ae409865e4c7493db061913d77a79";

/** Accept public voice-page links without fetching the page or its media. */
export function fishVoiceId(value: string): string {
  const text = value.trim();
  if (!/^https?:\/\//i.test(text)) return text;
  try {
    const url = new URL(text);
    const match = url.pathname.match(
      /^\/(?:[a-z]{2}(?:-[a-z]{2})?\/|app\/)?m\/([a-f\d]{32})\/?$/i,
    );
    if (
      url.protocol === "https:" &&
      ["fish.audio", "www.fish.audio"].includes(url.hostname) &&
      !url.username &&
      !url.password &&
      !url.port &&
      match
    )
      return match[1].toLowerCase();
  } catch {
    /* Show the same actionable message for malformed URLs. */
  }
  throw new Error(
    "Вставьте ссылку на голос вида https://fish.audio/ru/m/ID/ или сам ID голоса",
  );
}
