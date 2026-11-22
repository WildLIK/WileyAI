import test from "node:test";
import assert from "node:assert/strict";
import { EndpointDetector } from "../../src/voice/endpoint.ts";

function feed(detector: EndpointDetector, milliseconds: number, score: number, level = .03) {
  const results: Float32Array[] = [];
  for (let at = 0; at < milliseconds; at += 32) {
    const result = detector.push(new Float32Array(512).fill(level), score);
    if (result) results.push(result);
  }
  return results;
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

test("short commands end once on a pause over loud music, retaining pre-roll and a bounded real tail", () => {
  const detector = new EndpointDetector(16000, { mode: "auto" });
  feed(detector, 500, .02); feed(detector, 400, .95, .12);
  const results = feed(detector, 1200, .02);
  assert.equal(results.length, 1); assert.ok(results[0].length > 16000 * .5);
  assert.ok(results[0].length < 16000 * 1.1, "the 900 ms wait is not sent as a long STT tail");
  assert.equal(detector.isSpeaking, false);
});
test("an ordinary mid-sentence pause is kept; long meaningful speech is not cut after a few seconds", () => {
  const detector = new EndpointDetector(16000, { mode: "auto", maximumSpeechMs: 60000 });
  assert.deepEqual(feed(detector, 5000, .9), []);
  assert.deepEqual(feed(detector, 750, .02), []);
  assert.deepEqual(feed(detector, 10000, .9), []);
  assert.equal(feed(detector, 1200, .02).length, 1);
});
test("continuous fan/music, silence and a single loud click never create a speech turn", () => {
  const detector = new EndpointDetector(16000, {});
  assert.deepEqual(feed(detector, 16000, .01, .15), []);
  assert.deepEqual(feed(detector, 32, .99, .4), []);
  assert.deepEqual(feed(detector, 3000, .01, 0), []);
  assert.equal(detector.isSpeaking, false);
});
test("capture still has a hard memory bound, with distinct command and dictation pause budgets", () => {
  const detector = new EndpointDetector(16000, { mode: "dictation", maximumSpeechMs: 2000 });
  assert.equal(feed(detector, 2050, .9).length, 1);
  assert.equal(detector.diagnostics.reason, "maximum");
  assert.ok(new EndpointDetector(16000, { mode: "commands" }).pauseMs < detector.pauseMs);
});
test("Smart Turn runs once per pause, only after speech, and releases a completed phrase once", async () => {
  let checks = 0; const sent: Float32Array[] = [];
  const detector = new EndpointDetector(16000, {}, async () => { checks++; return true; }, (audio) => sent.push(audio));
  feed(detector, 5000, .01); assert.equal(checks, 0);
  feed(detector, 400, .9); feed(detector, 550, .01); await tick();
  assert.equal(checks, 1); assert.equal(sent.length, 1);
  assert.equal(feed(detector, 3000, .01).length, 0); assert.equal(sent.length, 1);
});
test("an incomplete turn gets extra time, but the silence deadline wins over the model", async () => {
  const sent: Float32Array[] = [];
  const detector = new EndpointDetector(16000, {}, async () => false, (audio) => sent.push(audio));
  feed(detector, 400, .9); feed(detector, 550, .01); await tick();
  assert.equal(feed(detector, 500, .01).length, 0);
  assert.equal(feed(detector, 900, .01).length, 1); assert.equal(sent.length, 0);
  assert.equal(detector.diagnostics.reason, "silence_limit");
});
test("missing and slow Smart Turn fall back to VAD without a second STT dispatch", async () => {
  for (const slow of [false, true]) {
    const detector = new EndpointDetector(16000, {}, slow ? () => new Promise(() => {}) : async () => null);
    feed(detector, 400, .9); feed(detector, 550, .01);
    await new Promise((resolve) => setTimeout(resolve, slow ? 380 : 5));
    assert.equal(feed(detector, 600, .01).length, 1);
    assert.equal(feed(detector, 2000, .01).length, 0);
  }
});
test("resumed speech and explicit cancellation invalidate an old semantic decision", async () => {
  const complete: ((value: boolean) => void)[] = []; let sends = 0;
  const detector = new EndpointDetector(16000, {}, () => new Promise((resolve) => complete.push(resolve)), () => sends++);
  feed(detector, 400, .9); feed(detector, 550, .01); await tick();
  feed(detector, 400, .9); complete[0](true); await tick();
  assert.equal(sends, 0); assert.equal(detector.isSpeaking, true);
  feed(detector, 550, .01); await tick(); detector.reset(); complete[1](true); await tick();
  assert.equal(sends, 0); assert.equal(detector.isSpeaking, false);
});
