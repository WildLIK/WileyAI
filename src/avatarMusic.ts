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

/** One stream per visible renderer; the backend shares one native metering worker. */
export class AvatarMusic {
  value = { ...silentMusic };
  private controller?: AbortController;
  private retry?: ReturnType<typeof setTimeout>;
  setEnabled(enabled: boolean) {
    if (enabled === Boolean(this.controller)) return;
    if (!enabled) {
      this.controller?.abort();
      this.controller = undefined;
      clearTimeout(this.retry);
      this.value = { ...silentMusic };
      return;
    }
    const controller = (this.controller = new AbortController());
    const connect = async () => {
      try {
        const { url, token } = await window.wiley.connection();
        const response = await fetch(url + "/avatar/music", {
          headers: { Authorization: "Bearer " + token },
          signal: controller.signal,
        });
        if (!response.ok || !response.body)
          throw new Error("Music meter unavailable");
        const reader = response.body.getReader(),
          decoder = new TextDecoder();
        let pending = "";
        try {
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            pending += decoder.decode(value, { stream: true });
            if (pending.length > 16384) throw new Error("Invalid meter stream");
            const frames = pending.split("\n\n");
            pending = frames.pop() || "";
            for (const frame of frames) {
              if (!frame.startsWith("data: ")) continue;
              const data = JSON.parse(frame.slice(6));
              if (
                data.type !== "music" ||
                ![data.level, data.beat, data.phase].every(Number.isFinite)
              )
                continue;
              this.value = {
                active: data.active === true,
                source: String(data.source || "").slice(0, 80),
                level: Math.min(1, Math.max(0, data.level)),
                beat: Math.min(1, Math.max(0, data.beat)),
                phase: data.phase,
                bpm: Number.isFinite(data.bpm) ? data.bpm : null,
                error: String(data.error || "").slice(0, 160),
                players: Array.isArray(data.players)
                  ? data.players
                      .slice(0, 16)
                      .map((player: unknown) => String(player).slice(0, 80))
                  : [],
              };
            }
          }
        } finally {
          await reader.cancel().catch(() => {});
        }
      } catch {
        /* A stopped/restarting local core is retried while visible. */
      }
      if (!controller.signal.aborted) {
        this.value = { ...silentMusic, error: "Нет связи с измерителем звука" };
        this.retry = setTimeout(() => void connect(), 2000);
      }
    };
    void connect();
  }
}
