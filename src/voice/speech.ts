export type SpeechOptions = {
  threshold?: number;
  silenceMs?: number;
  minimumSpeechMs?: number;
  maximumSpeechMs?: number;
  preRollMs?: number;
  noiseCalibrationMs?: number;
};

export function rms(samples: Float32Array): number {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / Math.max(samples.length, 1));
}

/** Bounded local energy gate. Whisper performs the subsequent neural VAD. */
export class SpeechSegmenter {
  readonly sampleRate: number;
  readonly options: Required<SpeechOptions>;
  private preRoll: Float32Array[] = [];
  private frames: Float32Array[] = [];
  private duration = 0;
  private speechDuration = 0;
  private silence = 0;
  private noiseFloor = 0.002;
  private calibratedMs = 0;
  private calibration: number[] = [];
  isSpeaking = false;

  get calibrating() {
    return this.calibratedMs < this.options.noiseCalibrationMs;
  }

  constructor(sampleRate: number, options: SpeechOptions = {}) {
    this.sampleRate = sampleRate;
    this.options = {
      threshold: options.threshold ?? 0.015,
      silenceMs: options.silenceMs ?? 1000,
      minimumSpeechMs: options.minimumSpeechMs ?? 160,
      maximumSpeechMs: options.maximumSpeechMs ?? 25000,
      preRollMs: options.preRollMs ?? 320,
      noiseCalibrationMs: options.noiseCalibrationMs ?? 0,
    };
  }

  reset() {
    this.frames = [];
    this.preRoll = [];
    this.duration = this.speechDuration = this.silence = 0;
    this.isSpeaking = false;
  }

  push(samples: Float32Array): Float32Array | null {
    if (!samples.length) return null;
    const ms = (samples.length / this.sampleRate) * 1000;
    const level = rms(samples);
    if (this.calibratedMs < this.options.noiseCalibrationMs) {
      this.calibratedMs += ms;
      this.calibration.push(level);
      // A median tolerates brief clicks during the initial background sample.
      const sorted = [...this.calibration].sort((a, b) => a - b);
      this.noiseFloor = sorted[Math.floor(sorted.length / 2)];
      if (this.calibratedMs >= this.options.noiseCalibrationMs)
        this.calibration = [];
      return null;
    }
    const margin = this.options.noiseCalibrationMs
      ? this.isSpeaking
        ? 1.4
        : 1.9
      : 3;
    const threshold = Math.max(
      this.options.threshold,
      this.noiseFloor * margin,
    );
    const audible = level >= threshold;
    if (!this.isSpeaking) {
      this.preRoll.push(samples);
      while (
        this.preRoll.reduce((count, frame) => count + frame.length, 0) >
        (this.options.preRollMs / 1000) * this.sampleRate
      )
        this.preRoll.shift();
      if (!audible) {
        this.noiseFloor = this.noiseFloor * 0.98 + level * 0.02;
        return null;
      }
      this.isSpeaking = true;
      this.frames = this.preRoll;
      this.preRoll = [];
      this.duration =
        (this.frames.reduce((count, frame) => count + frame.length, 0) /
          this.sampleRate) *
        1000;
      this.speechDuration = ms;
      this.silence = 0;
      return null;
    }
    this.frames.push(samples);
    this.duration += ms;
    if (audible) {
      this.speechDuration += ms;
      this.silence = 0;
    } else this.silence += ms;
    if (
      this.silence < this.options.silenceMs &&
      this.duration < this.options.maximumSpeechMs
    )
      return null;
    const result =
      this.speechDuration >= this.options.minimumSpeechMs
        ? joinFrames(this.frames)
        : null;
    this.reset();
    return result;
  }
}

export function joinFrames(frames: Float32Array[]): Float32Array {
  const result = new Float32Array(
    frames.reduce((count, frame) => count + frame.length, 0),
  );
  let offset = 0;
  for (const frame of frames) {
    result.set(frame, offset);
    offset += frame.length;
  }
  return result;
}

export function wav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index++)
      view.setUint8(offset + index, value.charCodeAt(index));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const value = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, value * (value < 0 ? 32768 : 32767), true);
  });
  return buffer;
}
