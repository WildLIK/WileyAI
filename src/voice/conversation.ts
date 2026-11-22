import { SpeechSegmenter, wav, type SpeechOptions } from "./speech.ts";
import type { Capture } from "./microphone.ts";
import { EndpointDetector, type CompletionCheck, type EndpointMode, type VoiceDiagnostics } from "./endpoint.ts";
import type { FrameVad, VadFactory } from "./vad.ts";
import { VadFailure } from "./vad.ts";
import type { ActivationDecision } from "./activation.ts";
import { VoiceTrace, type VoiceEvent, type VoiceEventDetails, type VoiceEventName } from "./diagnostics.ts";

export type Phase =
  | "idle"
  | "preparing"
  | "calibrating"
  | "listening"
  | "awaiting"
  | "hearing"
  | "pause"
  | "checking"
  | "executing"
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
export type VoiceTranscription = string | { text: string; rejectionReason?: string; rejectedCharacters?: number };
export const phaseLabels: Record<Phase, string> = {
  idle: "Разговор выключен",
  preparing: "Готовлю голос и модель…",
  calibrating: "Измеряю фон · помолчите",
  listening: "Ожидаю следующую реплику",
  awaiting: "Жду обращения",
  hearing: "Слышу речь…",
  pause: "Обнаружена пауза…",
  checking: "Проверяю завершение фразы…",
  executing: "Выполняю команду…",
  transcribing: "Распознаю речь…",
  thinking: "Обрабатываю запрос…",
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
    utteranceId?: number,
  ) => Promise<void>;
  onPhase: (phase: Phase) => void;
  onError: (error: unknown) => void;
  /** A failed utterance is reported without surrendering the microphone lease. */
  onRecover?: (error: unknown) => void;
  speech?: SpeechOptions;
  cooldownMs?: number;
  listenWhileThinking?: boolean;
  queueMode?: "sequential" | "latest" | "queue";
  pendingMaxAgeMs?: number;
  onPending?: (count: number, full: boolean) => void;
  onBarge?: (
    audio: Blob,
    signal: AbortSignal,
    playback: string,
  ) => Promise<string | null>;
  /** Recognize a phrase queued during an answer right away, not after it. */
  transcribe?: (audio: Blob, signal: AbortSignal) => Promise<VoiceTranscription>;
  createVad?: VadFactory;
  endpointMode?: EndpointMode;
  smartTurn?: CompletionCheck;
  onDiagnostics?: (value: VoiceDiagnostics) => void;
  onWarning?: (message: string) => void;
  sttTimeoutMs?: number;
  captureTimeoutMs?: number;
  requireActivation?: boolean;
  activation?: (text: string) => ActivationDecision;
  onEvent?: (event: VoiceEvent) => void;
  sttEngine?: string;
};

/** `text`: null — recognized as empty; undefined — not recognized in advance. */
type Utterance = {
  samples: Float32Array;
  excludeText?: string;
  capturedAt?: number;
  text?: Promise<{ text?: string | null; error?: unknown }>;
};

export class Conversation {
  private recordings = new WeakMap<Float32Array, Blob>();
  active = false;
  phase: Phase = "idle";
  private version = 0;
  private controller: AbortController | null = null;
  private segmenter: SpeechSegmenter | EndpointDetector | null = null;
  private options: Options;
  private working = false;
  private cooling = false;
  private pending: Utterance[] = [];
  private queueController: AbortController | null = null;
  private bargeSegmenter: SpeechSegmenter | EndpointDetector | null = null;
  private bargeController: AbortController | null = null;
  private playback = "";
  private vad: FrameVad | null = null;
  private heartbeat: ReturnType<typeof setInterval> | undefined;
  private lastFrameAt = 0;
  private recognitionTail: Promise<unknown> = Promise.resolve();
  private diagnosticAt = 0;
  private turnCapturedAt = 0;
  private firstAudio = false;
  private diagnostic: VoiceDiagnostics = { engine: "rms", level: 0, durationMs: 0, silenceMs: 0, lastVoiceAgoMs: 0, phase: "waiting" };
  private trace = new VoiceTrace();
  private finalized = new WeakMap<object, number>();
  private detectorPhase = new WeakMap<object, string>();
  private utteranceIds = new WeakMap<Float32Array, number>();
  private audioIds = new WeakMap<Blob, number>();
  private utteranceSequence = 0;
  private currentText = "";
  private get queuesEnabled() { return this.options.listenWhileThinking && this.options.queueMode !== "sequential"; }
  event(name: VoiceEventName, details?: VoiceEventDetails) {
    const event = this.trace.add(name, details);
    this.options.onEvent?.(event);
  }
  get events() { return this.trace.events; }

  setPlayback(text: string) {
    this.playback = (this.playback + " " + text).slice(-2400);
  }

  constructor(options: Options) {
    this.options = options;
  }
  private transition(phase: Phase) {
    if (phase === "listening" && this.options.requireActivation) phase = "awaiting";
    if (phase === "thinking" && this.queuesEnabled)
      phase = this.pending.length ? "queued" : "thinking_listening";
    // Never retain a partial microphone phrase across our own audio playback.
    if (phase === "speaking") { if (this.phase !== "speaking") this.event("response_started"); this.segmenter?.reset(); this.vad?.reset(); }
    if (phase !== "speaking") { this.bargeSegmenter?.reset(); this.bargeController?.abort(); }
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
      if (this.options.createVad) {
        try {
          const began = performance.now();
          const vad = await this.options.createVad(
            (frame, score, milliseconds) => { if (this.active && version === this.version) this.receiveScored(frame, score, milliseconds); },
            (error, pending) => { if (this.active && version === this.version) this.fallback(error, pending); },
            controller.signal,
          );
          if (!this.active || version !== this.version) { vad.dispose(); return; }
          this.vad = vad;
          this.event("vad_ready", { engine: "silero", milliseconds: performance.now() - began });
        } catch (error) {
          if (!this.active || version !== this.version || controller.signal.aborted) return;
          this.event("vad_initialization_failed", { reason: error instanceof VadFailure ? error.code : "initialization_failed" });
          this.event("vad_fallback_rms", { engine: "rms", reason: "initialization_failed" });
          this.options.onWarning?.("Локальный VAD недоступен. Используется резервный RMS-детектор. Причина указана в диагностике голоса.");
        }
      }
      await this.options.capture.start(
        (frame) => this.receive(frame),
        (error) => {
          void this.fail(error, version, "capture_error");
        },
      );
      if (!this.active || version !== this.version) return;
      if (this.vad && this.options.capture.sampleRate !== 16000) {
        this.vad.dispose(); this.vad = null;
        this.event("vad_fallback_rms", { engine: "rms", reason: "unsupported_sample_rate" });
        this.options.onWarning?.("Частота захвата отличается от 16 кГц. Используется резервный RMS-детектор.");
      }
      this.segmenter = this.vad ? new EndpointDetector(this.options.capture.sampleRate, { ...this.options.speech, mode: this.options.endpointMode }, this.options.smartTurn, (audio) => this.accept(audio), (name, details) => this.event(name, details)) : new SpeechSegmenter(
        this.options.capture.sampleRate,
        this.options.speech,
      );
      this.bargeSegmenter = this.options.onBarge
        ? this.vad ? new EndpointDetector(this.options.capture.sampleRate, { mode: "commands", silenceMs: 550, minimumSpeechMs: 300, maximumSpeechMs: 6000 }, undefined, () => {}) : new SpeechSegmenter(this.options.capture.sampleRate, {
            threshold: (this.options.speech?.threshold ?? 0.015) * 1.4,
            silenceMs: 450,
            minimumSpeechMs: 300,
            maximumSpeechMs: 6000,
            preRollMs: 320,
          })
        : null;
      this.transition(this.segmenter.calibrating ? "calibrating" : "listening");
      this.lastFrameAt = performance.now();
      this.heartbeat = setInterval(() => {
        if (this.active && performance.now() - this.lastFrameAt > (this.options.captureTimeoutMs ?? 2000))
          { void this.fail(new Error("Микрофон перестал передавать звук. Проверьте устройство и включите разговор заново."), version, "capture_stalled"); }
      }, 250);
    } catch (error) {
      if (this.active && version === this.version)
        await this.fail(error, version, "preparation_failed");
    }
  }
  private receive(frame: Float32Array) {
    this.lastFrameAt = performance.now();
    if (!this.active || this.cooling || this.phase === "preparing") return;
    if (this.phase === "speaking" && !this.bargeSegmenter) return;
    if (this.working && this.phase !== "speaking" && !this.queuesEnabled) return;
    if (this.vad) this.vad.push(frame);
    else this.receiveScored(frame);
  }
  private fallback(error: unknown, pending: Float32Array[]) {
    const reason = error instanceof VadFailure ? error.code : "worker_error";
    if (reason === "worker_timeout") this.event("vad_timeout", error instanceof VadFailure ? { reason, ...error.details } : { reason });
    this.event("vad_fallback_rms", { reason, engine: "rms", ...(error instanceof VadFailure ? error.details : {}) });
    const current = this.phase === "speaking" ? this.bargeSegmenter : this.segmenter;
    const previous = current instanceof EndpointDetector ? current.handover() : null;
    this.vad?.dispose(); this.vad = null; this.segmenter?.reset(); this.bargeSegmenter?.reset();
    this.segmenter = new SpeechSegmenter(this.options.capture.sampleRate, { ...this.options.speech, noiseCalibrationMs: 0 });
    this.bargeSegmenter = this.options.onBarge ? new SpeechSegmenter(this.options.capture.sampleRate, { threshold: (this.options.speech?.threshold ?? 0.015) * 1.4, silenceMs: 450, minimumSpeechMs: 300, maximumSpeechMs: 6000, preRollMs: 320 }) : null;
    const replacement = this.phase === "speaking" ? this.bargeSegmenter : this.segmenter;
    if (previous && replacement instanceof SpeechSegmenter) replacement.resume(previous);
    this.options.onWarning?.(`Включён резервный RMS (${reason}). Подтверждённая речь сохранена; Silero проверится при следующем запуске разговора.`);
    for (const frame of pending) this.receiveScored(frame);
  }
  private receiveScored(frame: Float32Array, score?: number, milliseconds?: number) {
    if (milliseconds !== undefined) this.diagnostic.vadMs = milliseconds;
    if (
      this.active &&
      !this.cooling &&
      this.phase === "speaking" &&
      this.bargeSegmenter
    ) {
      if (!this.bargeController) {
        const wasSpeaking = this.bargeSegmenter.isSpeaking;
        const samples = this.bargeSegmenter instanceof EndpointDetector ? this.bargeSegmenter.push(frame, score) : this.bargeSegmenter.push(frame);
        this.detected(this.bargeSegmenter, wasSpeaking, samples, "barge");
        if (samples) void this.checkBarge(samples);
      }
      return;
    }
    if (
      !this.active ||
      !this.segmenter ||
      this.cooling ||
      ["preparing", "speaking"].includes(this.phase) ||
      (this.working && !this.queuesEnabled)
    )
      return;
    const wasSpeaking = this.segmenter.isSpeaking;
    const utterance = this.segmenter instanceof EndpointDetector ? this.segmenter.push(frame, score) : this.segmenter.push(frame);
    this.detected(this.segmenter, wasSpeaking, utterance);
    if (this.segmenter instanceof EndpointDetector) this.diagnostic = { ...this.diagnostic, ...this.segmenter.diagnostics };
    else this.diagnostic = { ...this.diagnostic, engine: "rms", score: undefined, level: Math.sqrt(frame.reduce((sum, value) => sum + value * value, 0) / Math.max(1, frame.length)), durationMs: this.segmenter.durationMs, silenceMs: utterance ? this.segmenter.lastEndPauseMs : this.segmenter.pauseMs, lastVoiceAgoMs: this.segmenter.pauseMs, reason: utterance ? this.segmenter.finalization?.reason : this.diagnostic.reason, phase: this.segmenter.isSpeaking ? this.segmenter.pauseMs >= 160 ? "pause" : "speech" : "waiting" };
    this.report();
    if (this.segmenter.calibrating) return;
    if (utterance) {
      this.accept(utterance);
      return;
    }
    if (this.working) return;
    const phase = this.segmenter instanceof EndpointDetector && this.segmenter.checking ? "checking" : this.diagnostic.phase === "pause" ? "pause" : this.segmenter.isSpeaking ? "hearing" : "listening";
    if (phase !== this.phase) this.transition(phase);
  }
  private id(samples: Float32Array) {
    let id = this.utteranceIds.get(samples);
    if (!id) { id = ++this.utteranceSequence; this.utteranceIds.set(samples, id); }
    return id;
  }
  private detected(detector: SpeechSegmenter | EndpointDetector, wasSpeaking: boolean, samples: Float32Array | null, role = "main") {
    const engine = detector instanceof EndpointDetector ? "silero" : "rms";
    if (!wasSpeaking && detector.isSpeaking) this.event("speech_started", { engine, role });
    const phase = detector instanceof EndpointDetector ? detector.diagnostics.phase : detector.pauseMs >= 160 && detector.isSpeaking ? "pause" : "speech";
    if (phase === "pause" && this.detectorPhase.get(detector) !== "pause") this.event("pause_detected", { engine, role });
    this.detectorPhase.set(detector, phase);
    const end = detector.finalization;
    if (end && this.finalized.get(detector) !== end.sequence) {
      this.finalized.set(detector, end.sequence);
      if (!end.accepted) this.diagnostic.reason = "too_short";
      this.event(end.accepted ? "utterance_finalized" : "utterance_rejected", { engine, role, reason: end.accepted ? end.reason : "too_short", durationMs: samples ? samples.length / this.options.capture.sampleRate * 1000 : end.durationMs, voicedMs: end.voicedMs, ...(samples ? { utterance: this.id(samples) } : {}) });
    }
  }
  private report(force = false) {
    if (force || performance.now() - this.diagnosticAt > 200) {
      this.diagnosticAt = performance.now(); this.options.onDiagnostics?.({ ...this.diagnostic });
    }
  }
  private accept(utterance: Float32Array) {
    if (!this.active || this.cooling || this.phase === "speaking") return;
    if (this.segmenter instanceof EndpointDetector) { this.detected(this.segmenter, false, utterance); this.diagnostic = { ...this.diagnostic, ...this.segmenter.diagnostics }; this.report(true); }
    if (this.working) {
        if (!this.queuesEnabled) return;
        if (this.options.queueMode === "latest") {
          this.dropQueue();
          this.pending = [{ samples: utterance, capturedAt: performance.now(), excludeText: this.currentText }];
        } else if (this.pending.length < 3) this.pending.push(this.queued(utterance));
        this.options.onPending?.(
          this.pending.length,
          this.pending.length === 3,
        );
        this.transition("queued");
    } else void this.turn({ samples: utterance, capturedAt: performance.now() - this.diagnostic.silenceMs });
  }
  private blob(samples: Float32Array) {
    let blob = this.recordings.get(samples);
    if (blob) return blob;
    blob = new Blob([wav(samples, this.options.capture.sampleRate)], {
      type: "audio/wav",
    });
    this.recordings.set(samples, blob);
    this.audioIds.set(blob, this.id(samples));
    return blob;
  }
  private recognize(audio: Blob, parent: AbortSignal): Promise<string> {
    const controller = new AbortController();
    let cancel: () => void = () => {};
    const cancelled = new Promise<never>((_resolve, reject) => {
      cancel = () => { controller.abort(); reject(new DOMException("Распознавание отменено", "AbortError")); };
      parent.addEventListener("abort", cancel, { once: true });
      if (parent.aborted) cancel();
    });
    const work = this.recognitionTail.then(async () => {
      parent.throwIfAborted();
      const began = performance.now();
      const seconds = Math.max(0, audio.size - 44) / (2 * this.options.capture.sampleRate);
      const metadata = { utterance: this.audioIds.get(audio), durationMs: seconds * 1000, engine: this.options.sttEngine, role: "main" };
      this.event("stt_started", metadata);
      const limit = this.options.sttTimeoutMs ?? Math.min(90000, Math.max(20000, seconds * 2500));
      let timer: ReturnType<typeof setTimeout>;
      let timedOut = false;
      try {
        const result = await Promise.race([
          this.options.transcribe!(audio, controller.signal),
          new Promise<never>((_resolve, reject) => { timer = setTimeout(() => { timedOut = true; controller.abort(); reject(new Error("Распознавание речи не ответило вовремя. Фраза повторно не отправляется; можно произнести новую.")); }, limit); }),
          cancelled,
        ]);
        parent.throwIfAborted();
        const text = typeof result === "string" ? result : result.text;
        if (typeof text !== "string") throw new Error("STT вернул некорректный текст");
        this.event("stt_completed", { ...metadata, characters: text.length, milliseconds: performance.now() - began });
        if (typeof result !== "string" && result.rejectionReason) {
          this.event("stt_rejected", { ...metadata, reason: result.rejectionReason, characters: result.rejectedCharacters }); return "";
        }
        if (!text.trim()) { this.event("stt_empty", { ...metadata, reason: "empty" }); return ""; }
        const decision = this.options.activation?.(text) ?? { accepted: true, reason: "caller_verified" };
        if (this.working && this.currentText && text.trim().toLocaleLowerCase("ru-RU") === this.currentText) {
          this.event("request_cancelled", { reason: "duplicate_queued" }); return "";
        }
        this.event(decision.accepted ? "activation_accepted" : "activation_rejected", { ...metadata, reason: decision.reason, required: this.options.requireActivation });
        return decision.accepted ? text : "";
      } catch (error) {
        this.event(parent.aborted && !timedOut ? "request_cancelled" : "stt_failed", { ...metadata, reason: timedOut ? "stt_timeout" : parent.aborted ? this.active ? "user_cancelled" : "session_stale" : error instanceof TypeError ? "server_unavailable" : "stt_error" });
        throw error;
      } finally {
        clearTimeout(timer!);
        if (this.active && !parent.aborted) { this.diagnostic.sttMs = Math.round(performance.now() - began); this.report(true); }
      }
    });
    this.recognitionTail = work.catch(() => {});
    return Promise.race([work, cancelled]).finally(() => parent.removeEventListener("abort", cancel));
  }
  /** Start recognition while the current answer is still running. */
  private queued(samples: Float32Array): Utterance {
    const transcribe = this.options.transcribe;
    const capturedAt = performance.now() - this.diagnostic.silenceMs;
    if (!transcribe) return { samples, capturedAt };
    this.queueController ??= new AbortController();
    const item: Utterance = { samples, capturedAt };
    const text = this.recognize(this.blob(samples), this.queueController.signal)
      .then((value) => {
        if (!value.trim()) {
          const index = this.pending.indexOf(item);
          if (index >= 0) {
            this.pending.splice(index, 1); this.options.onPending?.(this.pending.length, false);
            if (this.working && this.phase === "queued" && !this.pending.length) this.transition("thinking");
          }
        }
        return { text: value.trim() || null };
      })
      .catch((error) => ({ error }));
    item.text = text;
    return item;
  }
  private async turn(utterance: Utterance) {
    const version = this.version;
    const controller = new AbortController();
    this.controller = controller;
    this.working = true;
    this.turnCapturedAt = utterance.capturedAt ?? performance.now(); this.firstAudio = false;
    this.playback = "";
    this.transition("transcribing");
    try {
      let recognized: string | null | undefined;
      if (utterance.text) {
        const result = await utterance.text;
        if (result.error) throw result.error;
        recognized = result.text;
        if (
          !this.active ||
          version !== this.version ||
          controller.signal.aborted
        )
          return;
        // Noise or an empty phrase recognized in advance never becomes a turn.
        if (recognized === null) return;
      } else if (this.options.transcribe) {
        recognized = (await this.recognize(this.blob(utterance.samples), controller.signal)).trim() || null;
        if (!recognized) return;
      }
      if (!this.active || version !== this.version || controller.signal.aborted) return;
      if (recognized && utterance.excludeText && recognized.trim().toLocaleLowerCase("ru-RU") === utterance.excludeText) { this.event("request_cancelled", { reason: "duplicate_queued" }); return; }
      this.currentText = recognized?.trim().toLocaleLowerCase("ru-RU") || "";
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
        this.id(utterance.samples),
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
      } else {
        // Only capture/preparation failures own the whole session. A failed
        // command, STT or TTS is never retried and must not close the lease.
        const wasSpeaking = this.phase === "speaking";
        controller.abort();
        this.dropQueue();
        this.segmenter?.reset(); this.bargeSegmenter?.reset(); this.vad?.reset();
        this.event("turn_recovered", { reason: "turn_error" });
        this.options.onRecover?.(error);
        if (wasSpeaking) {
          this.cooling = true;
          await new Promise(resolve => setTimeout(resolve, this.options.cooldownMs ?? 300));
        }
      }
    } finally {
      if (this.active && version === this.version) {
        this.working = this.cooling = false;
        this.currentText = "";
        this.pending = this.pending.filter((item) => {
          const fresh = performance.now() - (item.capturedAt ?? performance.now()) <= (this.options.pendingMaxAgeMs ?? 15000);
          if (!fresh) this.event("request_cancelled", { reason: "queued_expired" });
          return fresh;
        });
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
    const capturedAt = performance.now();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const accepted = await Promise.race([this.options.onBarge!(
        this.blob(samples),
        controller.signal,
        this.playback,
      ), new Promise<null>((resolve) => { timer = setTimeout(() => { controller.abort(); resolve(null); }, this.options.sttTimeoutMs ?? 20000); })]);
      if (
        accepted &&
        this.active &&
        version === this.version &&
        this.phase === "speaking" &&
        !controller.signal.aborted
      ) {
        this.controller?.abort();
        this.dropQueue();
        this.pending = [{ samples, text: Promise.resolve({ text: accepted }), capturedAt }];
        this.options.onPending?.(0, false);
      }
    } catch {
      // An unavailable verifier never stops playback or executes an unverified phrase.
    } finally {
      clearTimeout(timer);
      if (this.bargeController === controller) this.bargeController = null;
      this.bargeSegmenter?.reset();
    }
  }
  /** Delay playback until a microphone phrase already in progress is complete. */
  async waitForPhrase(signal: AbortSignal) {
    const began = performance.now();
    // Let a phrase already started during thinking finish before playing TTS.
    // SpeechSegmenter bounds it to the configured duration; stop aborts this wait.
    while (
      this.active &&
      this.queuesEnabled &&
      (this.segmenter?.isSpeaking || (this.segmenter instanceof EndpointDetector && this.segmenter.hasSpeechCandidate))
    ) {
      signal.throwIfAborted();
      if (performance.now() - began > (this.options.speech?.maximumSpeechMs ?? 60000) + 4000)
        throw new Error("Не удалось завершить захват реплики. Проверьте микрофон и режим VAD.");
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
    this.diagnostic.followupWaitMs = Math.round(performance.now() - began);
    if (!this.firstAudio) { this.diagnostic.responseWaitMs = Math.round(performance.now() - this.turnCapturedAt); this.firstAudio = true; }
    this.report(true);
  }

  /** Interrupt just the current answer, retaining the explicitly enabled session. */
  interrupt() {
    if (!this.active || this.phase === "preparing") return;
    this.event("request_cancelled", { reason: "user_cancelled" });
    this.controller?.abort();
    this.bargeController?.abort();
    this.dropQueue();
    this.options.onPending?.(0, false);
    this.segmenter?.reset();
    // A pending turn owns this transition until its cancellation has completed.
    this.vad?.reset();
    if (["listening", "awaiting", "hearing", "pause", "checking"].includes(this.phase))
      this.transition("listening");
  }
  private dropQueue() {
    this.pending = [];
    this.queueController?.abort();
    this.queueController = null;
  }
  private async fail(error: unknown, version: number, reason: string) {
    if (version !== this.version) return;
    await this.stop(reason);
    this.options.onError(error);
  }
  async stop(reason = "user_cancelled") {
    if (this.active) { this.event("request_cancelled", { reason }); this.event("session_stopped", { reason }); }
    this.active = false;
    this.version++;
    this.controller?.abort();
    this.bargeController?.abort();
    this.bargeController = null;
    this.bargeSegmenter = null;
    this.controller = null;
    this.dropQueue();
    clearInterval(this.heartbeat); this.heartbeat = undefined;
    this.vad?.dispose(); this.vad = null;
    this.working = this.cooling = false;
    this.options.onPending?.(0, false);
    this.segmenter?.reset();
    this.segmenter = null;
    this.transition("idle");
    await this.options.capture.stop();
  }
}
