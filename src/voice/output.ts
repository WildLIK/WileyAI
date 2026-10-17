/** Sentence buffering and bounded audio prefetch shared by chat and voice turns. */
export class SpeechText {
  private pending = "";
  private received = "";
  private firstRemaining: number;
  constructor(firstCharacters = 0) {
    this.firstRemaining = firstCharacters;
  }
  push(delta: string, final = false): string[] {
    this.received += delta;
    this.pending += delta;
    const chunks: string[] = [];
    while (this.pending) {
      const limit =
        this.firstRemaining > 0 ? Math.max(40, this.firstRemaining) : 240;
      let end = 0;
      for (const match of this.pending.matchAll(
        /[.!?…]+["»”*)\]]*(?:\s+)|\n+/g,
      )) {
        const before = this.pending.slice(0, match.index);
        // A decimal, initial or common abbreviation should stay with its sentence.
        if (
          match[0].startsWith(".") &&
          /(?:^|\s)(?:\d+|[А-ЯЁа-яёA-Za-z]{1,2}|руб|рис|стр|им)$/u.test(before)
        )
          continue;
        end = match.index! + match[0].length;
        break;
      }
      if ((!end || end > limit) && this.pending.length > limit) {
        end = this.pending.lastIndexOf(" ", limit);
        if (end < Math.min(100, limit / 2)) end = limit;
      }
      if (!end && final) end = this.pending.length;
      if (!end) break;
      const text = this.pending.slice(0, end).trim();
      this.pending = this.pending.slice(end);
      if (/[\p{L}\p{N}]/u.test(text)) {
        chunks.push(text);
        this.firstRemaining = Math.max(
          0,
          this.firstRemaining - text.length - 1,
        );
      }
    }
    return chunks;
  }
  finish(complete?: string): string[] {
    // Local commands can have a done event without deltas.
    const tail = complete?.startsWith(this.received)
      ? complete.slice(this.received.length)
      : "";
    return this.push(tail, true);
  }
}

export class SpeechOutput<T> {
  readonly controller = new AbortController();
  readonly done: Promise<void>;
  private text: SpeechText;
  private chunks: string[] = [];
  private closed = false;
  private wake = () => {};
  private synthesize: (text: string, signal: AbortSignal) => Promise<T>;
  private play: (audio: T, signal: AbortSignal) => Promise<void>;
  private batchCharacters = 0;
  private rendered = 0;
  private firstCharacters: number;
  private firstMinimum: number;
  private firstWaitMs: number;
  constructor(
    synthesize: (text: string, signal: AbortSignal) => Promise<T>,
    play: (audio: T, signal: AbortSignal) => Promise<void>,
    signal?: AbortSignal,
    options?: {
      batchCharacters?: number;
      firstCharacters?: number;
      firstMinimum?: number;
      firstWaitMs?: number;
    },
  ) {
    this.synthesize = synthesize;
    this.play = play;
    this.batchCharacters = options?.batchCharacters || 0;
    this.firstCharacters = options?.firstCharacters || 160;
    this.firstMinimum = options?.firstMinimum || 0;
    this.firstWaitMs = options?.firstWaitMs || 0;
    this.text = new SpeechText(options?.firstCharacters);
    const cancel = () => this.cancel();
    this.controller.signal.addEventListener("abort", () => this.wake(), {
      once: true,
    });
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) this.cancel();
    this.done = this.consume().finally(() =>
      signal?.removeEventListener("abort", cancel),
    );
    // The owner can await completion later, after the text stream ends.
    void this.done.catch(() => {});
  }
  push(delta: string) {
    if (this.closed || this.controller.signal.aborted) return;
    this.chunks.push(...this.text.push(delta));
    this.wake();
  }
  finish(complete?: string) {
    if (this.closed) return;
    this.chunks.push(...this.text.finish(complete));
    this.closed = true;
    this.wake();
  }
  whole(text: string) {
    if (this.closed || this.controller.signal.aborted) return;
    this.chunks.push(text);
    this.closed = true;
    this.wake();
  }
  cancel() {
    this.controller.abort();
    this.wake();
  }
  private async consume() {
    const signal = this.controller.signal;
    let playing = Promise.resolve();
    let playbackError: unknown;
    try {
      while (true) {
        signal.throwIfAborted();
        if (!this.chunks.length) {
          if (this.closed) break;
          await new Promise<void>((resolve) => {
            this.wake = resolve;
          });
          continue;
        }
        // Give a tiny acknowledgement a bounded chance to join the actual reply.
        // A complete short answer and a substantive first sentence never wait.
        if (
          !this.rendered &&
          !this.closed &&
          this.firstWaitMs &&
          this.firstMinimum
        ) {
          const until = performance.now() + this.firstWaitMs;
          while (
            !this.closed &&
            this.chunks.join(" ").length < this.firstMinimum
          ) {
            signal.throwIfAborted();
            const remaining = until - performance.now();
            if (remaining <= 0) break;
            await new Promise<void>((resolve) => {
              const ready = () => {
                clearTimeout(timer);
                resolve();
              };
              const timer = setTimeout(ready, remaining);
              this.wake = ready;
            });
          }
        }
        signal.throwIfAborted();
        let text = this.chunks.shift()!;
        // Coalesce an existing backlog without waiting for more text. The first
        // audio stays short; later phrases amortize model/API request overhead.
        const limit = this.rendered
          ? this.batchCharacters
          : Math.min(this.firstCharacters, this.batchCharacters);
        while (
          limit &&
          this.chunks.length &&
          text.length + this.chunks[0].length + 1 <= limit
        )
          text += " " + this.chunks.shift()!;
        this.rendered++;
        const audio = await this.synthesize(text, signal);
        signal.throwIfAborted();
        await playing;
        signal.throwIfAborted();
        playing = this.play(audio, signal);
        void playing.catch((error) => {
          playbackError = error;
          this.cancel();
        });
        // Prepare at most one next audio segment during playback.
      }
      await playing;
      signal.throwIfAborted();
    } catch (error) {
      this.cancel();
      await playing.catch(() => {});
      throw playbackError || error;
    }
  }
}
