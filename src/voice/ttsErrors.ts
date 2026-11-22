export class SpeechUnavailable extends Error {
  readonly retryAfterMs: number;
  readonly rateLimited: boolean;
  constructor(message: string, retryAfterMs = 0, rateLimited = false) {
    super(message); this.name = "SpeechUnavailable";
    this.retryAfterMs = retryAfterMs; this.rateLimited = rateLimited;
  }
}

export function retryAfterMs(value: string | null, now = Date.now()) {
  if (!value) return 30000;
  const numeric = Number(value);
  const result = Number.isFinite(numeric) ? numeric * 1000 : Date.parse(value) - now;
  return Number.isFinite(result) ? Math.min(86400000, Math.max(0, result)) : 30000;
}

/** No retries; the next explicit turn remains text-only during Retry-After. */
export class SpeechCooldown {
  private until = new Map<string, number>();
  check(key: string, now = Date.now()) {
    const remaining = (this.until.get(key) || 0) - now;
    if (remaining > 0) throw new SpeechUnavailable("Озвучка временно недоступна из-за лимита сервиса. Ответ сохранён текстом; разговор активен.", remaining, true);
    this.until.delete(key);
  }
  limit(key: string, milliseconds: number, now = Date.now()) { this.until.set(key, now + milliseconds); }
}
