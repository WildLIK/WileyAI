export type FrameVad = {
  push(frame: Float32Array): void;
  reset(): void;
  dispose(): void;
};
export type VadFactory = (
  scored: (samples: Float32Array, score: number, milliseconds?: number) => void,
  failed: (error: unknown, pending: Float32Array[]) => void,
  signal?: AbortSignal,
) => Promise<FrameVad>;

export class VadFailure extends Error {
  readonly code: string;
  readonly details: { queueFrames: number; oldestMs: number };
  constructor(code: string, message: string, details = { queueFrames: 0, oldestMs: 0 }) {
    super(message); this.name = "VadFailure"; this.code = code; this.details = details;
  }
}

/** A single local worker; neither the microphone nor an HTTP service is opened here. */
export const createLocalVad: VadFactory = async (scored, failed, signal) => {
  const worker = new Worker(new URL("./vad-worker.ts", import.meta.url), { type: "module" });
  let id = 0, epoch = 0, closed = false, tail = new Float32Array(0);
  const waiting = new Map<number, Float32Array>();
  const submitted = new Map<number, number>();
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const dispose = () => { closed = true; clearTimeout(watchdog); signal?.removeEventListener("abort", dispose); worker.terminate(); waiting.clear(); submitted.clear(); tail = new Float32Array(0); };
  const error = (code: string, message: string) => new VadFailure(code, message, { queueFrames: waiting.size, oldestMs: Math.round(performance.now() - (submitted.values().next().value ?? performance.now())) });
  const failure = (error: unknown) => {
    if (closed) return;
    const audio = [...waiting.values(), ...(tail.length ? [tail] : [])];
    dispose(); failed(error, audio);
  };
  await new Promise<void>((resolve, reject) => {
    const cancel = () => { clearTimeout(timer); dispose(); reject(new DOMException("Подготовка VAD отменена", "AbortError")); };
    const timer = setTimeout(() => { dispose(); signal?.removeEventListener("abort", cancel); reject(error("initialization_timeout", "VAD не ответил при подготовке")); }, 5000);
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) { cancel(); return; }
    worker.onerror = () => { clearTimeout(timer); signal?.removeEventListener("abort", cancel); dispose(); reject(error("initialization_failed", "Не удалось подготовить локальный VAD")); };
    worker.onmessage = ({ data }) => {
      if (data.ready) { clearTimeout(timer); signal?.removeEventListener("abort", cancel); resolve(); }
      else if (data.error) { clearTimeout(timer); signal?.removeEventListener("abort", cancel); dispose(); reject(error("initialization_failed", "Не удалось подготовить локальный VAD")); }
    };
  });
  signal?.addEventListener("abort", dispose, { once: true });
  const arm = () => {
    clearTimeout(watchdog); watchdog = undefined;
    if (!waiting.size || closed) return;
    const oldest = submitted.values().next().value!;
    const currentEpoch = epoch;
    watchdog = setTimeout(() => {
      // Allow already queued Worker messages one event-loop turn after a UI stall.
      watchdog = setTimeout(() => {
        if (!closed && epoch === currentEpoch && waiting.size && performance.now() - submitted.values().next().value! >= 500)
          failure(error("worker_timeout", "VAD не ответил за 500 мс"));
        else arm();
      }, 0);
    }, Math.max(1, 500 - (performance.now() - oldest)));
  };
  worker.onerror = () => failure(error("worker_error", "Локальный VAD остановился"));
  worker.onmessage = ({ data }) => {
    if (closed) return;
    if (data.epoch !== undefined && data.epoch !== epoch) return;
    if (data.error) { failure(error("inference_failed", "Ошибка вычисления локального VAD")); return; }
    if (data.epoch !== epoch) return;
    if (!Number.isFinite(data.score) || data.score < 0 || data.score > 1) { failure(error("invalid_score", "VAD вернул некорректную оценку")); return; }
    const audio = waiting.get(data.id); waiting.delete(data.id);
    submitted.delete(data.id); arm();
    if (audio) scored(audio, data.score, data.milliseconds);
  };
  return {
    push(frame) {
      if (closed) return;
      const audio = new Float32Array(tail.length + frame.length); audio.set(tail); audio.set(frame, tail.length);
      let at = 0;
      while (at + 512 <= audio.length) {
        const part = audio.slice(at, at + 512); at += 512;
        waiting.set(++id, part);
        submitted.set(id, performance.now());
        worker.postMessage({ id, epoch, audio: part });
      }
      tail = audio.slice(at);
      // Two seconds of *audio* (128 KiB) tolerates burst delivery after a UI pause.
      // Wall-clock inference deadline remains 500 ms, measured from oldest input.
      if (waiting.size > 64) { failure(error("queue_overflow", "Переполнен буфер PCM для VAD")); return; }
      if (waiting.size && !watchdog) arm();
    },
    reset() { epoch++; waiting.clear(); submitted.clear(); tail = new Float32Array(0); clearTimeout(watchdog); watchdog = undefined; worker.postMessage({ reset: true }); },
    dispose,
  };
};
