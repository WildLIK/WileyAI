import type { SpeechOutput } from "./output";

/** Routes the actual stream to TTS; display deltas never enter brief action speech. */
export class TurnSpeech<T> {
  private action = false;
  private readFull = false;
  private spoken = "";
  private status = "";
  private started = false;
  private output?: SpeechOutput<T>;
  private finished = false;
  private readonly mode: "brief" | "full" | "off";
  private readonly start: (force?: boolean) => SpeechOutput<T> | undefined;
  private readonly signal: AbortSignal;
  constructor(
    mode: "brief" | "full" | "off",
    start: (force?: boolean) => SpeechOutput<T> | undefined,
    signal: AbortSignal,
  ) { this.mode = mode; this.start = start; this.signal = signal; }
  event(event: { type: string; mode?: string; text?: string; action?: { spoken?: string; status?: string } }) {
    if (this.finished || this.signal.aborted) return;
    if (event.type === "speech_mode" && event.mode === "action") this.action = true;
    if (event.type === "speech_mode" && event.mode === "read_full") this.readFull = true;
    if (event.type === "speech_result") { this.spoken = event.action?.spoken || ""; this.status = event.action?.status || ""; }
    if (event.type === "speech_start" && this.action && this.mode === "brief" && event.text) {
      this.output ||= this.start();
      if (this.output) { this.started = true; this.output.push(event.text + " "); }
    }
    if (event.type === "delta" && event.text && !this.readFull && (!this.action || this.mode === "full")) {
      this.output ||= this.start();
      this.output?.push(event.text);
    }
  }
  finish(display: string) {
    if (this.finished || this.signal.aborted) return;
    this.finished = true;
    if (this.action && !this.readFull && this.mode === "off") return;
    if (this.readFull || (this.action && this.mode === "brief")) {
      if (this.readFull) {
        if (!this.spoken) return;
        this.output ||= this.start(true);
        this.output?.finish(this.spoken);
        return;
      }
      if (this.started && this.output) {
        if (this.spoken && this.status !== "process_started") this.output.push(this.spoken + " ");
        this.output.finish();
        return;
      }
      if (!this.spoken) return;
      this.output ||= this.start();
      this.output?.whole(this.spoken);
    } else {
      this.output ||= this.start();
      this.output?.finish(display);
    }
  }
  cancel() { this.finished = true; this.output?.cancel(); }
  get done() { return this.output?.done; }
}
