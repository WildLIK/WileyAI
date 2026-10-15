import test from "node:test";
import assert from "node:assert/strict";
import { Conversation, type Phase } from "../../src/voice/conversation.ts";
import type { Capture } from "../../src/voice/microphone.ts";

class FakeCapture implements Capture {
  sampleRate = 16000;
  starts = 0;
  stops = 0;
  receive: ((frame: Float32Array) => void) | null = null;
  async start(receive: (frame: Float32Array) => void) {
    this.starts++;
    this.receive = receive;
  }
  async stop() {
    this.stops++;
    this.receive = null;
  }
  push(count: number, volume: number) {
    for (let index = 0; index < count; index++)
      this.receive?.(new Float32Array(320).fill(volume));
  }
  utterance() {
    this.push(20, 0.1);
    this.push(50, 0);
  }
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

test("one phrase at a time; own audio during thinking/speaking is discarded", async () => {
  const capture = new FakeCapture();
  let turns = 0;
  let finish: () => void = () => {};
  const phases: Phase[] = [];
  const session = new Conversation({
    capture,
    prepare: async () => {},
    onPhase: (phase) => phases.push(phase),
    onError: (error) => {
      throw error;
    },
    cooldownMs: 0,
    onTurn: async (audio, signal, phase) => {
      turns++;
      assert.ok(audio.size > 44);
      phase("thinking");
      phase("speaking");
      await new Promise<void>((resolve) => {
        finish = resolve;
        signal.addEventListener("abort", resolve, { once: true });
      });
    },
  });
  await session.start();
  capture.utterance();
  assert.equal(session.phase, "speaking");
  capture.utterance();
  assert.equal(turns, 1);
  finish();
  await tick();
  assert.equal(session.phase, "listening");
  capture.utterance();
  assert.equal(turns, 2);
  await session.stop();
  finish();
  await tick();
  assert.equal(session.phase, "idle");
  assert.equal(capture.receive, null);
  assert.ok(phases.includes("hearing"));
});
test("stopping preparation cannot start the microphone later", async () => {
  const capture = new FakeCapture();
  let prepared: () => void = () => {};
  const session = new Conversation({
    capture,
    prepare: () => new Promise<void>((resolve) => (prepared = resolve)),
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    onTurn: async () => {
      throw new Error("Unexpected turn");
    },
  });
  const starting = session.start();
  await session.stop();
  prepared();
  await starting;
  assert.equal(capture.starts, 0);
  assert.equal(session.active, false);
  assert.equal(session.phase, "idle");
});
test("stopping ASR aborts the request and never resumes or starts a reply", async () => {
  const capture = new FakeCapture();
  let signal: AbortSignal | undefined;
  const session = new Conversation({
    capture,
    prepare: async () => {},
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    onTurn: async (_audio, current) => {
      signal = current;
      await new Promise<void>((_resolve, reject) =>
        current.addEventListener(
          "abort",
          () => reject(new DOMException("Stop", "AbortError")),
          { once: true },
        ),
      );
    },
  });
  await session.start();
  capture.utterance();
  await session.stop();
  await tick();
  assert.equal(signal?.aborted, true);
  assert.equal(session.phase, "idle");
  assert.equal(capture.receive, null);
});
test("interrupt cancels the current reply but keeps the explicitly enabled conversation", async () => {
  const capture = new FakeCapture();
  let errors = 0;
  const session = new Conversation({
    capture,
    prepare: async () => {},
    onPhase: () => {},
    onError: () => errors++,
    cooldownMs: 0,
    onTurn: async (_audio, signal, phase) => {
      phase("speaking");
      await new Promise<void>((_resolve, reject) =>
        signal.addEventListener(
          "abort",
          () => reject(new DOMException("Interrupt", "AbortError")),
          { once: true },
        ),
      );
    },
  });
  await session.start();
  capture.utterance();
  session.interrupt();
  await tick();
  assert.equal(session.active, true);
  assert.equal(session.phase, "listening");
  assert.equal(errors, 0);
  await session.stop();
});
test("ASR/provider failure stops the session rather than looping API requests", async () => {
  const capture = new FakeCapture();
  const errors: unknown[] = [];
  const session = new Conversation({
    capture,
    prepare: async () => {},
    onPhase: () => {},
    onError: (error) => errors.push(error),
    onTurn: async () => {
      throw new Error("Model offline");
    },
  });
  await session.start();
  capture.utterance();
  await tick();
  capture.utterance();
  assert.equal(errors.length, 1);
  assert.equal(session.active, false);
  assert.equal(capture.receive, null);
});
