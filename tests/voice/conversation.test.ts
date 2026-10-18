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

test("TTS waits for an in-progress follow-up phrase; cancellation releases the wait", async () => {
  const capture = new FakeCapture();
  let finish: () => void = () => {};
  const session = new Conversation({
    capture,
    listenWhileThinking: true,
    prepare: async () => {},
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    onTurn: async (_audio, _signal, phase) => {
      phase("thinking");
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    },
  });
  await session.start();
  capture.utterance();
  capture.push(20, 0.2);
  let ready = false;
  const controller = new AbortController();
  const waiting = session.waitForPhrase(controller.signal).then(() => {
    ready = true;
  });
  await tick();
  assert.equal(ready, false);
  capture.push(50, 0);
  await waiting;
  assert.equal(ready, true);
  assert.equal(session.phase, "queued");
  capture.push(20, 0.2);
  const cancelled = session.waitForPhrase(controller.signal);
  controller.abort();
  await assert.rejects(cancelled, { name: "AbortError" });
  await session.stop();
  finish();
  await tick();
});

test("continuous listening queues a bounded FIFO while thinking and never overlaps turns", async () => {
  const capture = new FakeCapture();
  let turns = 0;
  let active = 0;
  const finish: (() => void)[] = [];
  const queued: [number, boolean][] = [];
  const voices: number[] = [];
  const session = new Conversation({
    capture,
    listenWhileThinking: true,
    prepare: async () => {},
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    cooldownMs: 0,
    onPending: (count, full) => queued.push([count, full]),
    onTurn: async (audio, _signal, phase) => {
      assert.equal(++active, 1);
      voices.push(
        new Int16Array((await audio.arrayBuffer()).slice(44)).find(
          (value) => value !== 0,
        )!,
      );
      turns++;
      phase("thinking");
      await new Promise<void>((resolve) => finish.push(resolve));
      active--;
    },
  });
  await session.start();
  capture.utterance();
  await tick();
  assert.equal(session.phase, "thinking_listening");
  for (const volume of [0.2, 0.3, 0.4, 0.5]) {
    capture.push(20, volume);
    capture.push(50, 0);
  }
  assert.equal(turns, 1);
  assert.equal(session.phase, "queued");
  assert.deepEqual(queued.at(-1), [3, true]);
  for (let index = 0; index < 4; index++) {
    finish[index]();
    await tick();
  }
  assert.equal(turns, 4);
  assert.equal(session.phase, "listening");
  assert.deepEqual(
    voices,
    [0.1, 0.2, 0.3, 0.4].map((value) => Math.trunc(Math.fround(value) * 32767)),
  );
  await session.stop();
});

test("queued microphone audio is discarded on interrupt and stop, including late completion", async () => {
  for (const stop of [false, true]) {
    const capture = new FakeCapture();
    let turns = 0;
    let finish: () => void = () => {};
    let signal: AbortSignal | undefined;
    const session = new Conversation({
      capture,
      listenWhileThinking: true,
      prepare: async () => {},
      onPhase: () => {},
      onError: (error) => {
        throw error;
      },
      onTurn: async (_audio, current, phase) => {
        turns++;
        signal = current;
        phase("thinking");
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
      },
    });
    await session.start();
    capture.utterance();
    capture.utterance();
    assert.equal(session.phase, "queued");
    if (stop) await session.stop();
    else session.interrupt();
    assert.equal(signal?.aborted, true);
    finish();
    await tick();
    assert.equal(turns, 1);
    assert.equal(session.phase, stop ? "idle" : "listening");
    await session.stop();
  }
});

test("continuous mode rejects own playback and its tail but keeps an earlier queued phrase", async () => {
  const capture = new FakeCapture();
  let finish: () => void = () => {};
  let speak: () => void = () => {};
  let turns = 0;
  const session = new Conversation({
    capture,
    listenWhileThinking: true,
    prepare: async () => {},
    cooldownMs: 40,
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    onTurn: async (_audio, _signal, phase) => {
      turns++;
      phase("thinking");
      speak = () => phase("speaking");
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    },
  });
  await session.start();
  capture.utterance();
  capture.utterance();
  speak();
  capture.utterance();
  finish();
  await tick();
  capture.utterance(); // Echo during the post-playback cooldown.
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(turns, 2);
  await session.stop();
  finish();
  await tick();
});

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
