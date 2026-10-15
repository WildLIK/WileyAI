import { SpeechSegmenter, wav, type SpeechOptions } from "./speech.ts";
import type { Capture } from "./microphone.ts";

export type Phase =
  | "idle"
  | "preparing"
  | "listening"
  | "hearing"
  | "transcribing"
  | "thinking"
  | "speaking";
export type ConversationState = {
  active: boolean;
  owner: boolean;
  phase: Phase;
};
export const phaseLabels: Record<Phase, string> = {
  idle: "Разговор выключен",
  preparing: "Готовлю голос и модель…",
  listening: "Слушаю вас",
  hearing: "Слышу вашу фразу…",
  transcribing: "Распознаю речь…",
  thinking: "Обдумываю ответ…",
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
};

export class Conversation {
  active = false;
  phase: Phase = "idle";
  private version = 0;
  private controller: AbortController | null = null;
  private segmenter: SpeechSegmenter | null = null;
  private options: Options;

  constructor(options: Options) {
    this.options = options;
  }
  private transition(phase: Phase) {
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
      this.transition("listening");
    } catch (error) {
      if (this.active && version === this.version)
        await this.fail(error, version);
    }
  }
  private receive(frame: Float32Array) {
    if (
      !this.active ||
      !this.segmenter ||
      !["listening", "hearing"].includes(this.phase)
    )
      return;
    const utterance = this.segmenter.push(frame);
    if (utterance) {
      void this.turn(utterance);
      return;
    }
    const phase = this.segmenter.isSpeaking ? "hearing" : "listening";
    if (phase !== this.phase) this.transition(phase);
  }
  private async turn(samples: Float32Array) {
    const version = this.version;
    const controller = new AbortController();
    this.controller = controller;
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
      await new Promise((resolve) =>
        setTimeout(resolve, this.options.cooldownMs ?? 300),
      );
      if (!this.active || version !== this.version) return;
      this.segmenter?.reset();
      this.transition("listening");
    } catch (error) {
      if (!this.active || version !== this.version) return;
      if (controller.signal.aborted) {
        this.segmenter?.reset();
        this.transition("listening");
      } else await this.fail(error, version);
    }
  }
  /** Interrupt just the current answer, retaining the explicitly enabled session. */
  interrupt() {
    if (!this.active || this.phase === "preparing") return;
    this.controller?.abort();
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
    this.segmenter?.reset();
    this.segmenter = null;
    this.transition("idle");
    await this.options.capture.stop();
  }
}
