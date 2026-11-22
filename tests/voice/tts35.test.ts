import test from "node:test";
import assert from "node:assert/strict";
import { SpeechCooldown, SpeechUnavailable, retryAfterMs } from "../../src/voice/ttsErrors.ts";
import { SpeechOutput } from "../../src/voice/output.ts";

test("Retry-After accepts seconds/date and cooldown never changes providers", () => {
  assert.equal(retryAfterMs("7", 0), 7000);
  assert.equal(retryAfterMs("Thu, 01 Jan 1970 00:00:10 GMT", 0), 10000);
  assert.equal(retryAfterMs("invalid", 0), 30000);
  const gate = new SpeechCooldown(); gate.limit("one", 1000, 0);
  assert.throws(() => gate.check("one", 10), SpeechUnavailable);
  gate.check("two", 10); gate.check("one", 1000);
});
test("speech failure cancels prefetched speech without retry", async () => {
  const display = "Текст ответа. Ещё текст ответа."; let calls=0, played=0;
  const output = new SpeechOutput(async () => { calls++; throw new SpeechUnavailable("HTTP 429", 30000, true); }, async () => { played++; });
  output.finish(display);
  await assert.rejects(output.done, SpeechUnavailable);
  assert.equal(calls, 1); assert.equal(played, 0);
});
