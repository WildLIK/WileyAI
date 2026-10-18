import { SpeechSegmenter, wav, type SpeechOptions } from "./speech.ts";
import type { Capture } from "./microphone.ts";

export type Phase =
  | "idle"
  | "preparing"
  | "calibrating"
  | "listening"
  | "hearing"
  | "transcribing"
  | "thinking"
  | "thinking_listening"
  | "queued"
  | "speaking";
export type ConversationState = {
  active: boolean;
  owner: boolean;
  phase: Phase;
};
export const phaseLabels: Record<Phase, string> = {
  idle: "Разговор выключен",
  preparing: "Готовлю голос и модель…",
  calibrating: "Измеряю фон · помолчите",
  listening: "Слушаю вас",
  hearing: "Слышу вашу фразу…",
  transcribing: "Распознаю речь…",
  thinking: "Обдумываю ответ…",
  thinking_listening: "Думаю · слушаю вас",
  queued: "Следующая фраза в очереди",
  speaking: "Отвечаю вслух",
};

type Options = {
  capture: Capture;
  prepare: (signal: AbortSignal) => Promise<void>;
  onTurn: (
    audio: Blob,
    signal: AbortSignal,
    phase: (phase: Phase) => void,
  ) => Promise<void>;
  onPhase: (phase: Phase) => void;
  onError: (error: unknown) => void;
  speech?: SpeechOptions;
  cooldownMs?: number;
  listenWhileThinking?: boolean;
  onPending?: (count: number, full: boolean) => void;
};

export class Conversation {
  active = false;
  phase: Phase = "idle";
  private version = 0;
  private controller: AbortController | null = null;
  private segmenter: SpeechSegmenter | null = null;
  private options: Options;
  private working = false;
  private cooling = false;
  private pending: Float32Array[] = [];

  constructor(options: Options) {
    this.options = options;
  }
  private transition(phase: Phase) {
    if (phase === "thinking" && this.options.listenWhileThinking)
      phase = this.pending.length ? "queued" : "thinking_listening";
    // Never retain a partial microphone phrase across our own audio playback.
    if (phase === "speaking") this.segmenter?.reset();
    this.phase = phase;
    this.options.onPhase(phase);
  }
  async start() {
    if (this.active) return;
    const version = ++this.version;
    this.active = true;
    const controller = new AbortController();
    this.controller = controller;
    this.transition("preparing");
    try {
      await this.options.prepare(controller.signal);
      if (!this.active || version !== this.version) return;
      await this.options.capture.start(
        (frame) => this.receive(frame),
        (error) => {
          void this.fail(error, version);
        },
      );
      if (!this.active || version !== this.version) return;
      this.segmenter = new SpeechSegmenter(
        this.options.capture.sampleRate,
        this.options.speech,
      );
      this.transition(this.segmenter.calibrating ? "calibrating" : "listening");
    } catch (error) {
      if (this.active && version === this.version)
        await this.fail(error, version);
    }
  }
  private receive(frame: Float32Array) {
    if (
      !this.active ||
      !this.segmenter ||
      this.cooling ||
      ["preparing", "speaking"].includes(this.phase) ||
      (this.working && !this.options.listenWhileThinking)
    )
      return;
    const utterance = this.segmenter.push(frame);
    if (this.segmenter.calibrating) return;
    if (utterance) {
      if (this.working) {
        if (this.pending.length < 3) this.pending.push(utterance);
        this.options.onPending?.(
          this.pending.length,
          this.pending.length === 3,
        );
        this.transition("queued");
      } else void this.turn(utterance);
      return;
    }
    if (this.working) return;
    const phase = this.segmenter.isSpeaking ? "hearing" : "listening";
    if (phase !== this.phase) this.transition(phase);
  }
  private async turn(samples: Float32Array) {
    const version = this.version;
    const controller = new AbortController();
    this.controller = controller;
    this.working = true;
    this.transition("transcribing");
    try {
      await this.options.onTurn(
        new Blob([wav(samples, this.options.capture.sampleRate)], {
          type: "audio/wav",
        }),
        controller.signal,
        (phase) => {
          if (
            this.active &&
            version === this.version &&
            !controller.signal.aborted
          )
            this.transition(phase);
        },
      );
      if (!this.active || version !== this.version) return;
      if (this.phase === "speaking") {
        this.cooling = true;
        await new Promise((resolve) =>
          setTimeout(resolve, this.options.cooldownMs ?? 300),
        );
        if (!this.active || version !== this.version) return;
        this.segmenter?.reset();
      }
    } catch (error) {
      if (!this.active || version !== this.version) return;
      if (controller.signal.aborted) {
        this.segmenter?.reset();
      } else await this.fail(error, version);
    } finally {
      if (this.active && version === this.version) {
        this.working = this.cooling = false;
        const next = this.pending.shift();
        this.options.onPending?.(this.pending.length, false);
        if (next) void this.turn(next);
        else
          this.transition(this.segmenter?.isSpeaking ? "hearing" : "listening");
      }
    }
  }
  /** Delay playback until a microphone phrase already in progress is complete. */
  async waitForPhrase(signal: AbortSignal) {
    // Let a phrase already started during thinking finish before playing TTS.
    // SpeechSegmenter bounds it to 25 seconds; stop/interrupt aborts this wait.
    while (
      this.active &&
      this.options.listenWhileThinking &&
      this.segmenter?.isSpeaking
    ) {
      signal.throwIfAborted();
      await new Promise<void>((resolve, reject) => {
        const cancel = () => {
          clearTimeout(timer);
          reject(new DOMException("Ответ остановлен", "AbortError"));
        };
        const timer = setTimeout(() => {
          signal.removeEventListener("abort", cancel);
          resolve();
        }, 25);
        signal.addEventListener("abort", cancel, { once: true });
        if (signal.aborted) cancel();
      });
    }
    signal.throwIfAborted();
  }

  /** Interrupt just the current answer, retaining the explicitly enabled session. */
  interrupt() {
    if (!this.active || this.phase === "preparing") return;
    this.controller?.abort();
    this.pending = [];
    this.options.onPending?.(0, false);
    this.segmenter?.reset();
    // A pending turn owns this transition until its cancellation has completed.
    if (this.phase === "listening" || this.phase === "hearing")
      this.transition("listening");
  }
  private async fail(error: unknown, version: number) {
    if (version !== this.version) return;
    await this.stop();
    this.options.onError(error);
  }
  async stop() {
    this.active = false;
    this.version++;
    this.controller?.abort();
    this.controller = null;
    this.pending = [];
    this.working = this.cooling = false;
    this.options.onPending?.(0, false);
    this.segmenter?.reset();
    this.segmenter = null;
    this.transition("idle");
    await this.options.capture.stop();
  }
}
