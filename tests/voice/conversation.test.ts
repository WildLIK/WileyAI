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

test("neural barge-in ignores rejected playback and dispatches one verified new phrase", async () => {
  const capture = new FakeCapture(); const heard: (string | undefined)[] = []; let checks = 0;
  const session = new Conversation({ capture, cooldownMs: 0, prepare: async () => {}, onPhase: () => {}, onError: (error) => { throw error; },
    createVad: async (scored) => ({ push(frame) { scored(frame, frame[0] ? .95 : .01); }, reset() {}, dispose() {} }),
    onBarge: async () => ++checks === 1 ? null : "Уайли, следующий трек",
    onTurn: async (_audio, signal, phase, verified) => {
      heard.push(verified);
      if (heard.length === 1) {
        phase("speaking");
        await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
      }
    },
  });
  await session.start(); capture.utterance(); await tick();
  capture.utterance(); await tick(); assert.equal(heard.length, 1);
  capture.utterance(); await tick(); await tick();
  assert.deepEqual(heard, [undefined, "Уайли, следующий трек"]); assert.equal(checks, 2);
  await session.stop();
});

test("a stuck STT operation times out, cancels its request, and cannot dispatch a late command", async () => {
  const capture = new FakeCapture(); let calls = 0, turns = 0, errors = 0;
  let late: (text: string) => void = () => {}; let signal: AbortSignal | undefined;
  const session = new Conversation({ capture, sttTimeoutMs: 20, prepare: async () => {}, onPhase: () => {}, onError: () => {}, onRecover: () => errors++,
    transcribe: async (_audio, current) => { calls++; signal = current; return await new Promise((resolve) => { late = resolve; }); },
    onTurn: async () => { turns++; },
  });
  await session.start(); capture.utterance();
  await new Promise((resolve) => setTimeout(resolve, 45));
  // D1: a timed-out utterance is aborted, while a healthy capture remains open.
  assert.equal(session.active, true); assert.equal(capture.stops, 0); assert.equal(signal?.aborted, true); assert.equal(errors, 1);
  late("Открой Блендер"); await tick(); assert.equal(calls, 1); assert.equal(turns, 0);
  await session.stop();
});

test("VAD failure during a short interruption retains its onset before RMS verifies it once", async () => {
  const capture = new FakeCapture(); let barge = false, frames = 0, checks = 0, turns = 0;
  const session = new Conversation({ capture, cooldownMs: 0, prepare: async () => {}, onPhase: () => {}, onError: (error) => { throw error; },
    createVad: async (scored, failed) => ({ push(frame) {
      if (barge && ++frames === 11) failed(new Error("Worker failed during interruption"), [frame]);
      else scored(frame, frame[0] ? .95 : .01);
    }, reset() {}, dispose() {} }),
    onBarge: async (audio) => {
      checks++;
      const pcm = new Int16Array((await audio.arrayBuffer()).slice(44));
      assert.equal(pcm.filter((sample) => sample > 3000).length, 20 * 320, "all 400 ms of speech survive the worker failure");
      return "Уайли, следующий трек";
    },
    onTurn: async (_audio, signal, phase) => {
      if (++turns === 1) {
        phase("speaking"); barge = true;
        await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
      }
    },
  });
  try {
    await session.start(); capture.utterance(); await tick();
    capture.utterance(); await tick(); await tick();
    assert.equal(checks, 1); assert.equal(turns, 2);
  } finally { await session.stop(); }
});
test("stopping a queued recognition clears it without retries or an action after stop", async () => {
  const capture = new FakeCapture(); let count = 0, turns = 0; let finish: () => void = () => {}; let late: (text: string) => void = () => {};
  const session = new Conversation({ capture, listenWhileThinking: true, prepare: async () => {}, onPhase: () => {}, onError: () => {},
    transcribe: async () => ++count === 1 ? "Первая фраза" : await new Promise((resolve) => { late = resolve; }),
    onTurn: async (_audio, _signal, phase) => { turns++; phase("thinking"); await new Promise<void>((resolve) => { finish = resolve; }); },
  });
  await session.start(); capture.utterance(); await tick(); capture.utterance(); await tick();
  await session.stop(); late("Запусти музыку"); finish(); await tick();
  assert.equal(count, 2); assert.equal(turns, 1); assert.equal(session.phase, "idle");
});
test("failed queued STT is reported once and is not recognized a second time", async () => {
  const capture = new FakeCapture(); let count = 0, errors = 0, turns = 0; let finish: () => void = () => {};
  const session = new Conversation({ capture, listenWhileThinking: true, prepare: async () => {}, onPhase: () => {}, onError: () => {}, onRecover: () => errors++,
    transcribe: async () => { if (++count === 1) return "Первая фраза"; throw new Error("Offline"); },
    onTurn: async (_audio, _signal, phase) => { turns++; phase("thinking"); await new Promise<void>((resolve) => { finish = resolve; }); },
  });
  await session.start(); capture.utterance(); await tick(); capture.utterance(); await tick(); finish(); await tick();
  assert.equal(count, 2); assert.equal(turns, 1); assert.equal(errors, 1); assert.equal(session.active, true);
  await session.stop();
});
test("VAD initialization failure preserves an explicitly visible RMS fallback", async () => {
  const capture = new FakeCapture(); let turns = 0; const warnings: string[] = [];
  const session = new Conversation({ capture, prepare: async () => {}, onPhase: () => {}, onError: () => {}, onWarning: (text) => warnings.push(text),
    createVad: async () => { throw new Error("Model missing"); }, onTurn: async () => { turns++; },
  });
  await session.start(); capture.utterance(); await tick();
  assert.equal(turns, 1); assert.match(warnings[0], /RMS/); await session.stop();
});
test("a model failure mid-word retains buffered PCM and sends the phrase exactly once", async () => {
  const capture = new FakeCapture(); let frames = 0, disposed = 0, turns = 0;
  const session = new Conversation({ capture, prepare: async () => {}, onPhase: () => {}, onError: () => {},
    createVad: async (scored, failed) => ({ push(frame) { if (++frames === 11) failed(new Error("Worker failed"), [frame]); else scored(frame, frame[0] ? .9 : .01); }, reset() {}, dispose() { disposed++; } }),
    onTurn: async (audio) => { turns++; const pcm = new Int16Array((await audio.arrayBuffer()).slice(44)); assert.ok(pcm.some((value) => value > 3000)); },
  });
  await session.start(); capture.utterance(); await tick();
  assert.equal(turns, 1); assert.equal(disposed, 1); await session.stop();
});
test("stopping during VAD initialization disposes the late worker and never opens a microphone", async () => {
  const capture = new FakeCapture(); let ready: (value: { push(): void; reset(): void; dispose(): void }) => void = () => {}; let disposed = 0;
  const session = new Conversation({ capture, prepare: async () => {}, onPhase: () => {}, onError: () => {},
    createVad: () => new Promise((resolve) => { ready = resolve; }), onTurn: async () => { throw new Error("Late turn"); },
  });
  const starting = session.start(); await tick(); await session.stop();
  ready({ push() {}, reset() {}, dispose() { disposed++; } }); await starting;
  assert.equal(capture.starts, 0); assert.equal(disposed, 1); assert.equal(session.phase, "idle");
});
test("a stalled audio device stops the session and releases capture instead of waiting in hearing", async () => {
  const capture = new FakeCapture(); let errors = 0;
  const session = new Conversation({ capture, captureTimeoutMs: 10, prepare: async () => {}, onPhase: () => {}, onError: () => errors++, onTurn: async () => {} });
  await session.start(); capture.push(10, .1);
  await new Promise((resolve) => setTimeout(resolve, 290));
  assert.equal(session.active, false); assert.equal(capture.stops, 1); assert.equal(errors, 1);
});

test("verified voice interruption cancels playback, discards queued speech and uses exactly one verified transcript", async () => {
  const capture = new FakeCapture();
  let turns = 0,
    checks = 0,
    cancelled = false;
  const session = new Conversation({
    capture,
    prepare: async () => {},
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    onBarge: async (_audio, _signal, playback) => {
      checks++;
      assert.equal(playback, " Ответ о погоде");
      return "Уайли, пауза";
    },
    onTurn: async (_audio, signal, phase, verified) => {
      turns++;
      if (turns === 1) {
        session.setPlayback("Ответ о погоде");
        phase("speaking");
        await new Promise<void>((resolve) =>
          signal.addEventListener(
            "abort",
            () => {
              cancelled = true;
              resolve();
            },
            { once: true },
          ),
        );
        signal.throwIfAborted();
      } else assert.equal(verified, "Уайли, пауза");
    },
  });
  await session.start();
  capture.utterance();
  await tick();
  capture.utterance();
  await tick();
  await tick();
  assert.equal(checks, 1);
  assert.equal(turns, 2);
  assert.equal(cancelled, true);
  assert.equal(session.active, true);
  assert.equal(session.phase, "listening");
  await session.stop();
});

test("unverified playback does not interrupt; a late verifier cannot revive a stopped session", async () => {
  const capture = new FakeCapture();
  let verify: (value: string | null) => void = () => {},
    aborted = false;
  const session = new Conversation({
    capture,
    prepare: async () => {},
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    onBarge: async () =>
      new Promise((resolve) => {
        verify = resolve;
      }),
    onTurn: async (_audio, signal, phase) => {
      phase("speaking");
      await new Promise<void>((resolve) =>
        signal.addEventListener(
          "abort",
          () => {
            aborted = true;
            resolve();
          },
          { once: true },
        ),
      );
      signal.throwIfAborted();
    },
  });
  await session.start();
  capture.utterance();
  await tick();
  capture.utterance();
  await tick();
  verify(null);
  await tick();
  assert.equal(aborted, false);
  capture.utterance();
  await tick();
  await session.stop();
  verify("Уайли, открой блокнот");
  await tick();
  assert.equal(session.active, false);
  assert.equal(session.phase, "idle");
  assert.equal(aborted, true);
});

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
test("ASR/provider failure retains capture without automatically repeating a request", async () => {
  const capture = new FakeCapture();
  const errors: unknown[] = [];
  const session = new Conversation({
    capture,
    prepare: async () => {},
    onPhase: () => {},
    onError: () => {},
    onRecover: (error) => errors.push(error),
    onTurn: async () => {
      throw new Error("Model offline");
    },
  });
  await session.start();
  capture.utterance();
  await tick();
  assert.equal(errors.length, 1);
  assert.equal(session.active, true);
  assert.notEqual(capture.receive, null);
  await tick(); assert.equal(errors.length, 1, "no automatic retry");
  await session.stop();
});

test("phrases queued during an answer are recognized at once; empty ones never become turns", async () => {
  const capture = new FakeCapture();
  const recognized: string[] = ["Первая фраза", "", "Уайли, следующий трек"];
  let transcribed = 0;
  const heard: (string | undefined)[] = [];
  let finish: () => void = () => {};
  const session = new Conversation({
    capture,
    listenWhileThinking: true,
    prepare: async () => {},
    onPhase: () => {},
    onError: (error) => {
      throw error;
    },
    transcribe: async () => recognized[transcribed++],
    onTurn: async (_audio, _signal, phase, text) => {
      heard.push(text);
      if (heard.length === 1) {
        phase("thinking");
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
      }
    },
  });
  await session.start();
  capture.utterance(); // The first phrase is recognized by the same bounded path.
  await tick();
  capture.utterance(); // Noise while thinking.
  capture.utterance(); // A real request while thinking.
  await tick();
  assert.equal(
    transcribed,
    3,
    "both queued phrases were recognized before the answer ended",
  );
  finish();
  await tick();
  await tick();
  assert.deepEqual(heard, ["Первая фраза", "Уайли, следующий трек"]);
  assert.equal(session.phase, "listening");
  await session.stop();
});
