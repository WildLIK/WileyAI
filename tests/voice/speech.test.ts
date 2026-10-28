import test from "node:test";
import assert from "node:assert/strict";
import { SpeechSegmenter, rms, wav } from "../../src/voice/speech.ts";

const frame = (volume = 0) => new Float32Array(320).fill(volume);
function feed(segmenter: SpeechSegmenter, count: number, volume: number) {
  let result: Float32Array | null = null;
  for (let index = 0; index < count; index++)
    result = segmenter.push(frame(volume)) || result;
  return result;
}

test("silence and brief clicks do not become utterances", () => {
  const detector = new SpeechSegmenter(16000);
  assert.equal(feed(detector, 500, 0), null);
  assert.equal(feed(detector, 3, 0.1), null);
  assert.equal(feed(detector, 70, 0), null);
  assert.equal(detector.isSpeaking, false);
});
test("keeps a pre-roll and waits for an actual pause rather than cutting between words", () => {
  const detector = new SpeechSegmenter(16000, { silenceMs: 800 });
  feed(detector, 40, 0);
  assert.equal(feed(detector, 15, 0.08), null);
  assert.equal(detector.isSpeaking, true);
  assert.equal(feed(detector, 20, 0), null);
  assert.equal(feed(detector, 15, 0.08), null);
  const utterance = feed(detector, 40, 0);
  assert.ok(utterance);
  assert.ok(utterance.length > 16000); // Pre-roll, spoken words, inner and final pauses.
  assert.equal(utterance[0], 0);
  assert.equal(detector.isSpeaking, false);
});
test("bounds a continuous utterance and reset discards old samples", () => {
  const detector = new SpeechSegmenter(16000, { maximumSpeechMs: 1000 });
  const utterance = feed(detector, 50, 0.05);
  assert.equal(utterance?.length, 16000);
  feed(detector, 15, 0.05);
  detector.reset();
  assert.equal(feed(detector, 60, 0), null);
});
test("WAV is mono PCM16 with the correct sample rate and clipped samples", () => {
  const data = wav(new Float32Array([-2, 0, 0.5, 2]), 16000);
  const view = new DataView(data);
  assert.equal(new TextDecoder().decode(data.slice(0, 4)), "RIFF");
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint32(40, true), 8);
  assert.equal(view.getInt16(44, true), -32768);
  assert.equal(view.getInt16(50, true), 32767);
  assert.ok(Math.abs(rms(new Float32Array([0.1, -0.1])) - 0.1) < 1e-6);
});

test("music profile calibrates steady background and ends speech above it without waiting 25 seconds", () => {
  const detector = new SpeechSegmenter(16000, { noiseCalibrationMs: 600 });
  assert.equal(detector.calibrating, true);
  assert.equal(feed(detector, 30, 0.03), null);
  assert.equal(detector.calibrating, false);
  assert.equal(feed(detector, 150, 0.03), null);
  assert.equal(detector.isSpeaking, false);
  feed(detector, 20, 0.13);
  assert.equal(detector.isSpeaking, true);
  const utterance = feed(detector, 50, 0.03);
  assert.ok(utterance && utterance.length < 16000 * 2);
  assert.equal(detector.isSpeaking, false);
  detector.reset();
  assert.equal(detector.calibrating, false);
  assert.equal(feed(detector, 100, 0.03), null);
});

test("steady loud background that starts above the gate ends instead of becoming one endless phrase", () => {
  const detector = new SpeechSegmenter(16000, { maximumSpeechMs: 60000 });
  feed(detector, 50, 0.001);
  let utterance: Float32Array | null = null,
    frames = 0;
  while (!utterance && frames < 3000) {
    utterance = detector.push(frame(0.05));
    frames++;
  }
  assert.ok(utterance, "the phrase ended");
  assert.ok(
    frames * 20 < 5000,
    `ended after ${frames * 20} ms, not at the 60 s limit`,
  );
  // The same background no longer opens new phrases…
  assert.equal(feed(detector, 500, 0.05), null);
  assert.equal(detector.isSpeaking, false);
  // …while a voice above it still does.
  feed(detector, 30, 0.2);
  assert.equal(detector.isSpeaking, true);
  assert.ok(feed(detector, 60, 0.05));
});

test("a quiet word ending above the hold gate does not split a command", () => {
  const detector = new SpeechSegmenter(16000, { silenceMs: 600 });
  feed(detector, 20, 0);
  feed(detector, 20, 0.05);
  // Quieter than the start gate (0.015), louder than the hold gate.
  assert.equal(feed(detector, 40, 0.012), null);
  assert.equal(detector.isSpeaking, true);
  feed(detector, 20, 0.05);
  const utterance = feed(detector, 40, 0);
  assert.ok(utterance && utterance.length > 16000 * 1.5);
});
