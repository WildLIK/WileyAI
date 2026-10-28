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
    verifiedText?: string,
  ) => Promise<void>;
  onPhase: (phase: Phase) => void;
  onError: (error: unknown) => void;
  speech?: SpeechOptions;
  cooldownMs?: number;
  listenWhileThinking?: boolean;
  onPending?: (count: number, full: boolean) => void;
  onBarge?: (
    audio: Blob,
    signal: AbortSignal,
    playback: string,
  ) => Promise<string | null>;
  /** Recognize a phrase queued during an answer right away, not after it. */
  transcribe?: (audio: Blob, signal: AbortSignal) => Promise<string>;
};

/** `text`: null — recognized as empty; undefined — not recognized in advance. */
type Utterance = {
  samples: Float32Array;
  text?: Promise<string | null | undefined>;
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
  private pending: Utterance[] = [];
  private queueController: AbortController | null = null;
  private bargeSegmenter: SpeechSegmenter | null = null;
  private bargeController: AbortController | null = null;
  private playback = "";

  setPlayback(text: string) {
    this.playback = (this.playback + " " + text).slice(-2400);
  }

  constructor(options: Options) {
    this.options = options;
  }
  private transition(phase: Phase) {
    if (phase === "thinking" && this.options.listenWhileThinking)
      phase = this.pending.length ? "queued" : "thinking_listening";
    // Never retain a partial microphone phrase across our own audio playback.
    if (phase === "speaking") this.segmenter?.reset();
    if (phase !== "speaking") this.bargeSegmenter?.reset();
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
      this.bargeSegmenter = this.options.onBarge
        ? new SpeechSegmenter(this.options.capture.sampleRate, {
            threshold: (this.options.speech?.threshold ?? 0.015) * 1.4,
            silenceMs: 450,
            minimumSpeechMs: 300,
            maximumSpeechMs: 6000,
            preRollMs: 320,
          })
        : null;
      this.transition(this.segmenter.calibrating ? "calibrating" : "listening");
    } catch (error) {
      if (this.active && version === this.version)
        await this.fail(error, version);
    }
  }
  private receive(frame: Float32Array) {
    if (
      this.active &&
      !this.cooling &&
      this.phase === "speaking" &&
      this.bargeSegmenter
    ) {
      if (!this.bargeController) {
        const samples = this.bargeSegmenter.push(frame);
        if (samples) void this.checkBarge(samples);
      }
      return;
    }
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
        if (this.pending.length < 3) this.pending.push(this.queued(utterance));
        this.options.onPending?.(
          this.pending.length,
          this.pending.length === 3,
        );
        this.transition("queued");
      } else void this.turn({ samples: utterance });
      return;
    }
    if (this.working) return;
    const phase = this.segmenter.isSpeaking ? "hearing" : "listening";
    if (phase !== this.phase) this.transition(phase);
  }
  private blob(samples: Float32Array) {
    return new Blob([wav(samples, this.options.capture.sampleRate)], {
      type: "audio/wav",
    });
  }
  /** Start recognition while the current answer is still running. */
  private queued(samples: Float32Array): Utterance {
    const transcribe = this.options.transcribe;
    if (!transcribe) return { samples };
    this.queueController ??= new AbortController();
    const text = transcribe(this.blob(samples), this.queueController.signal)
      .then((value) => value.trim() || null)
      // An error is reported by the regular turn, which transcribes again.
      .catch(() => undefined);
    return { samples, text };
  }
  private async turn(utterance: Utterance) {
    const version = this.version;
    const controller = new AbortController();
    this.controller = controller;
    this.working = true;
    this.playback = "";
    this.transition("transcribing");
    try {
      let recognized: string | null | undefined;
      if (utterance.text) {
        recognized = await utterance.text;
        if (
          !this.active ||
          version !== this.version ||
          controller.signal.aborted
        )
          return;
        // Noise or an empty phrase recognized in advance never becomes a turn.
        if (recognized === null) return;
      }
      await this.options.onTurn(
        this.blob(utterance.samples),
        controller.signal,
        (phase) => {
          if (
            this.active &&
            version === this.version &&
            !controller.signal.aborted
          )
            this.transition(phase);
        },
        recognized ?? undefined,
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
  private async checkBarge(samples: Float32Array) {
    const controller = new AbortController(),
      version = this.version;
    this.bargeController = controller;
    try {
      const accepted = await this.options.onBarge!(
        this.blob(samples),
        controller.signal,
        this.playback,
      );
      if (
        accepted &&
        this.active &&
        version === this.version &&
        this.phase === "speaking" &&
        !controller.signal.aborted
      ) {
        this.controller?.abort();
        this.dropQueue();
        this.pending = [{ samples, text: Promise.resolve(accepted) }];
        this.options.onPending?.(0, false);
      }
    } catch {
      // An unavailable verifier never stops playback or executes an unverified phrase.
    } finally {
      if (this.bargeController === controller) this.bargeController = null;
      this.bargeSegmenter?.reset();
    }
  }
  /** Delay playback until a microphone phrase already in progress is complete. */
  async waitForPhrase(signal: AbortSignal) {
    // Let a phrase already started during thinking finish before playing TTS.
    // SpeechSegmenter bounds it to the configured duration; stop aborts this wait.
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
    this.bargeController?.abort();
    this.dropQueue();
    this.options.onPending?.(0, false);
    this.segmenter?.reset();
    // A pending turn owns this transition until its cancellation has completed.
    if (this.phase === "listening" || this.phase === "hearing")
      this.transition("listening");
  }
  private dropQueue() {
    this.pending = [];
    this.queueController?.abort();
    this.queueController = null;
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
    this.bargeController?.abort();
    this.bargeController = null;
    this.bargeSegmenter = null;
    this.controller = null;
    this.dropQueue();
    this.working = this.cooling = false;
    this.options.onPending?.(0, false);
    this.segmenter?.reset();
    this.segmenter = null;
    this.transition("idle");
    await this.options.capture.stop();
  }
}
