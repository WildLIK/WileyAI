export type MusicPulse = {
  active: boolean;
  source: string;
  level: number;
  beat: number;
  phase: number;
  bpm: number | null;
  error: string;
  players?: string[];
};
export const silentMusic: MusicPulse = {
  active: false,
  source: "",
  level: 0,
  beat: 0,
  phase: 0,
  bpm: null,
  error: "",
};

const staleMusic: MusicPulse = {
  ...silentMusic,
  error: "Данные измерителя звука устарели",
};
const disconnected: MusicPulse = {
  ...silentMusic,
  error: "Нет связи с измерителем звука",
};
const ttlMs = 1000;

/** One stream per visible renderer; neither heartbeats nor an old lease renew a sample. */
export class AvatarMusic {
  private pulse = silentMusic;
  private deadline = Infinity;
  private controller?: AbortController;
  private retry?: ReturnType<typeof setTimeout>;
  private readonly now: () => number;
  constructor(now = () => performance.now()) {
    this.now = now;
  }

  get value(): MusicPulse {
    return this.now() >= this.deadline ? staleMusic : this.pulse;
  }

  setEnabled(enabled: boolean) {
    if (enabled === Boolean(this.controller)) return;
    if (!enabled) {
      this.controller?.abort();
      this.controller = undefined;
      clearTimeout(this.retry);
      this.pulse = silentMusic;
      this.deadline = Infinity;
      return;
    }
    const owner = (this.controller = new AbortController());
    const connect = async () => {
      const attempt = new AbortController();
      const stop = () => {
        clearInterval(watchdog);
        attempt.abort();
      };
      owner.signal.addEventListener("abort", stop, { once: true });
      let lastFrame = this.now(),
        lastRevision = -1;
      const watchdog = setInterval(() => {
        if (this.now() - lastFrame >= 3000) stop();
      }, 1000);
      try {
        const { url, token } = await window.wiley.connection();
        if (attempt.signal.aborted) return;
        const response = await fetch(url + "/avatar/music", {
          headers: { Authorization: "Bearer " + token },
          signal: attempt.signal,
        });
        if (!response.ok || !response.body)
          throw new Error("Music meter unavailable");
        const reader = response.body.getReader(),
          decoder = new TextDecoder();
        let pending = "";
        try {
          while (!attempt.signal.aborted) {
            const { value, done } = await reader.read();
            if (done || attempt.signal.aborted) break;
            pending += decoder.decode(value, { stream: true });
            if (pending.length > 16384) throw new Error("Invalid meter stream");
            const frames = pending.split("\n\n");
            pending = frames.pop() || "";
            for (const frame of frames) {
              if (!frame.startsWith("data: ")) continue;
              const d = JSON.parse(frame.slice(6));
              if (
                d.type !== "music" ||
                ![d.level, d.beat, d.phase].every(Number.isFinite)
              )
                continue;
              const now = this.now();
              if (d.revision !== undefined) {
                if (
                  !Number.isSafeInteger(d.revision) ||
                  d.revision < lastRevision ||
                  !Number.isFinite(d.fresh_ms)
                )
                  continue;
                lastFrame = now;
                if (d.observation === "sample") {
                  const expires =
                    now + Math.max(0, Math.min(ttlMs, d.fresh_ms));
                  if (d.revision === lastRevision) {
                    this.deadline = Math.min(this.deadline, expires);
                    continue;
                  }
                  this.deadline = expires;
                } else {
                  // Unknown observations never drive motion, even if a producer sends levels.
                  lastRevision = d.revision;
                  this.deadline = Infinity;
                  this.pulse =
                    d.observation === "stale"
                      ? staleMusic
                      : d.observation === "error"
                        ? {
                            ...silentMusic,
                            error: "Не удалось прочитать уровень звука Windows",
                          }
                        : silentMusic;
                  continue;
                }
                lastRevision = d.revision;
              } else {
                // Older cores have transport freshness only.
                lastFrame = now;
                this.deadline = now + ttlMs;
              }
              this.pulse = {
                active: d.active === true,
                source: String(d.source || "").slice(0, 80),
                level: Math.min(1, Math.max(0, d.level)),
                beat: Math.min(1, Math.max(0, d.beat)),
                phase: d.phase,
                bpm: Number.isFinite(d.bpm) ? d.bpm : null,
                error: String(d.error || "").slice(0, 160),
                players: Array.isArray(d.players)
                  ? d.players
                      .slice(0, 16)
                      .map((p: unknown) => String(p).slice(0, 80))
                  : [],
              };
            }
          }
        } finally {
          await reader.cancel().catch(() => {});
        }
      } catch {
        /* A stopped/restarting local core is retried while visible. */
      } finally {
        clearInterval(watchdog);
        owner.signal.removeEventListener("abort", stop);
        if (!owner.signal.aborted) {
          this.pulse = disconnected;
          this.deadline = Infinity;
          this.retry = setTimeout(() => void connect(), 2000);
        }
      }
    };
    void connect();
  }
}
