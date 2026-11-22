import { joinFrames, rms, type SpeechOptions } from "./speech.ts";
import type { SpeechFinalization } from "./speech.ts";
import type { VoiceEventSink } from "./diagnostics.ts";

export type EndpointMode = "auto" | "commands" | "conversation" | "dictation";
export type EndpointReason = "pause" | "smart_complete" | "silence_limit" | "maximum";
export type VoiceDiagnostics = {
  engine: string; level: number; score?: number; durationMs: number;
  silenceMs: number; lastVoiceAgoMs: number; reason?: EndpointReason | "no_speech" | "too_short";
  phase: "waiting" | "speech" | "pause" | "checking";
  sttMs?: number; responseWaitMs?: number; detail?: string;
  vadMs?: number; smartTurnMs?: number; interpretationMs?: number; llmMs?: number; firstOutputMs?: number; ttsMs?: number; followupWaitMs?: number;
};
export type CompletionCheck = (audio: Float32Array, signal: AbortSignal) => Promise<boolean | null>;

/** Policy stays independent of the VAD model and is replayable from scored PCM. */
export class EndpointDetector {
  private frames: Float32Array[] = [];
  private pre: Float32Array[] = [];
  private elapsed = 0;
  private voiced = 0;
  private lastVoice = 0;
  private silence = 0;
  private onset = 0;
  private quiet = 0;
  private clock = 0;
  private voiceAt: number | null = null;
  private revision = 0;
  private check: AbortController | null = null;
  private checkedPause = false;
  private incomplete = false;
  private diagnostic: VoiceDiagnostics = { engine: "silero", level: 0, durationMs: 0, silenceMs: 0, lastVoiceAgoMs: 0, phase: "waiting" };
  readonly pauseMs: number;
  readonly silenceLimitMs: number;
  readonly sampleRate: number;
  readonly options: SpeechOptions & { mode?: EndpointMode };
  private complete?: CompletionCheck;
  private onComplete: (audio: Float32Array) => void;
  private onEvent?: VoiceEventSink;
  finalization: SpeechFinalization | null = null;
  isSpeaking = false;
  readonly calibrating = false;
  get diagnostics() { return { ...this.diagnostic }; }
  get checking() { return this.check !== null; }
  get hasSpeechCandidate() { return this.isSpeaking || this.onset > 0; }
  constructor(
    sampleRate: number,
    options: SpeechOptions & { mode?: EndpointMode },
    complete?: CompletionCheck,
    onComplete: (audio: Float32Array) => void = () => {},
    onEvent?: VoiceEventSink,
  ) {
    this.sampleRate = sampleRate; this.options = options; this.complete = complete; this.onComplete = onComplete; this.onEvent = onEvent;
    const pause = options.silenceMs ?? 1000;
    this.pauseMs = options.mode === "commands" ? Math.min(pause, 550)
      : options.mode === "dictation" ? Math.max(pause, 1800)
      : options.mode === "conversation" ? Math.max(pause, 1100) : Math.max(500, pause * .9);
    this.silenceLimitMs = Math.max(this.pauseMs, options.mode === "dictation" ? 3500 : 1800);
  }
  reset() {
    if (this.check && !this.check.signal.aborted) this.onEvent?.("smart_turn_cancelled", { reason: "segment_reset" });
    this.check?.abort(); this.check = null; this.revision++;
    this.frames = []; this.pre = []; this.elapsed = this.voiced = this.lastVoice = this.silence = this.onset = this.quiet = 0;
    this.checkedPause = this.incomplete = this.isSpeaking = false;
  }
  /** Retain the actual beginning if the model fails part-way through a phrase. */
  buffered() { return [...(this.isSpeaking ? this.frames : this.pre)]; }
  handover() { return { frames: this.buffered(), speaking: this.isSpeaking, voicedMs: this.voiced, silenceMs: this.silence }; }
  private finish(reason: EndpointReason) {
    const valid = this.voiced >= (this.options.minimumSpeechMs ?? 128);
    this.finalization = { sequence: (this.finalization?.sequence ?? 0) + 1, accepted: valid, durationMs: this.elapsed, voicedMs: this.voiced, reason };
    // Keep a short real tail, instead of sending an entire silence interval to STT.
    const samples = joinFrames(this.frames).slice(0, Math.ceil((this.lastVoice + 200) * this.sampleRate / 1000));
    this.reset();
    this.diagnostic = { ...this.diagnostic, phase: "waiting", durationMs: 0, reason: valid ? reason : "too_short" };
    return valid ? samples : null;
  }
  push(samples: Float32Array, score = 0): Float32Array | null {
    if (!samples.length) return null;
    const ms = samples.length / this.sampleRate * 1000;
    const voiced = score >= (this.isSpeaking ? .35 : .55);
    this.clock += ms; if (voiced) this.voiceAt = this.clock;
    this.diagnostic = { engine: "silero", level: rms(samples), score, durationMs: this.elapsed, silenceMs: this.silence, lastVoiceAgoMs: this.voiceAt === null ? -1 : this.clock - this.voiceAt, phase: this.isSpeaking ? "speech" : "waiting", reason: this.diagnostic.reason };
    if (!this.isSpeaking) {
      this.pre.push(samples);
      let length = this.pre.reduce((sum, item) => sum + item.length, 0);
      while (this.pre.length > 1 && length > (this.options.preRollMs ?? 320) * this.sampleRate / 1000) length -= this.pre.shift()!.length;
      this.onset = voiced ? this.onset + ms : 0;
      this.quiet = voiced ? 0 : this.quiet + ms;
      if (this.quiet >= 15000) { this.diagnostic.reason = "no_speech"; this.quiet = 0; }
      if (this.onset < 96) return null;
      this.isSpeaking = true; this.frames = this.pre; this.pre = [];
      this.diagnostic.reason = undefined;
      this.elapsed = length / this.sampleRate * 1000; this.voiced = this.onset; this.lastVoice = this.elapsed;
      return null;
    }
    this.frames.push(samples); this.elapsed += ms;
    if (voiced) {
      this.voiced += ms; this.lastVoice = this.elapsed; this.silence = 0;
      if (this.checkedPause || this.check) {
        if (this.check && !this.check.signal.aborted) this.onEvent?.("smart_turn_cancelled", { reason: "speech_resumed" });
        this.check?.abort(); this.check = null; this.revision++;
        this.checkedPause = this.incomplete = false;
      }
    } else this.silence += ms;
    this.diagnostic = { ...this.diagnostic, durationMs: this.elapsed, silenceMs: this.silence, phase: this.check ? "checking" : this.silence >= 160 ? "pause" : "speech" };
    if (this.elapsed >= (this.options.maximumSpeechMs ?? 60000)) return this.finish("maximum");
    if (this.silence >= this.silenceLimitMs) return this.finish("silence_limit");
    if (this.complete && !this.checkedPause && this.silence >= Math.min(this.pauseMs, 500)) {
      this.checkedPause = true;
      const revision = this.revision, controller = new AbortController(); this.check = controller;
      this.onEvent?.("smart_turn_started", { durationMs: Math.min(8000, this.elapsed) });
      // One call per actual pause, with a bounded deadline. Audio is never sent
      // outside the local core, and resumed speech invalidates this decision.
      const audio = joinFrames(this.frames).slice(-16000 * 8);
      let timer: ReturnType<typeof setTimeout>;
      const timeout = new Promise<null>((resolve) => {
        controller.signal.addEventListener("abort", () => { clearTimeout(timer); resolve(null); }, { once: true });
        timer = setTimeout(() => { this.onEvent?.("smart_turn_timeout", { milliseconds: 350 }); controller.abort(new DOMException("Smart Turn deadline", "TimeoutError")); resolve(null); }, 350);
      });
      void Promise.race([Promise.resolve().then(() => this.complete!(audio, controller.signal)), timeout])
        .catch(() => { if (!controller.signal.aborted) this.onEvent?.("smart_turn_failed", { reason: "inference_failed" }); return null; }).then((done) => {
          clearTimeout(timer);
          if (revision !== this.revision || !this.isSpeaking) return;
          this.onEvent?.("smart_turn_completed", { reason: done === true ? "complete" : done === false ? "incomplete" : "unavailable" });
          this.check = null; this.incomplete = done === false;
          if (done === true || (done === null && this.silence >= this.pauseMs)) {
            const result = this.finish(done === true ? "smart_complete" : "pause");
            if (result) this.onComplete(result);
          }
        });
    }
    if (!this.check && !this.incomplete && this.silence >= this.pauseMs) return this.finish("pause");
    return null;
  }
}
