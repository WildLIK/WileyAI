import test from "node:test";
import assert from "node:assert/strict";
import { Conversation, type Phase } from "../../src/voice/conversation.ts";
import { createLocalVad } from "../../src/voice/vad.ts";
import { VadFailure } from "../../src/voice/vad.ts";
import { activated, inspectActivation } from "../../src/voice/activation.ts";
import { VoiceTrace } from "../../src/voice/diagnostics.ts";
import { readFile } from "node:fs/promises";
import { EndpointDetector } from "../../src/voice/endpoint.ts";

const tick = () => new Promise((resolve) => setTimeout(resolve, 10));
class Capture {
  sampleRate = 16000;
  receive: ((frame: Float32Array) => void) | null = null;
  async start(receive: (frame: Float32Array) => void) { this.receive = receive; }
  async stop() { this.receive = null; }
  push(count: number, volume: number) {
    for (let i = 0; i < count; i++) this.receive?.(new Float32Array(320).fill(volume));
  }
}

test("confirmed quiet speech survives Silero failure and reaches STT once with its complete onset", async () => {
  const capture = new Capture(), phases: Phase[] = [];
  let frames = 0, stt = 0, turns = 0, quietSamples = 0;
  const session = new Conversation({ capture, prepare: async () => {}, requireActivation: true, cooldownMs: 0,
    speech: { threshold: .015, minimumSpeechMs: 300, silenceMs: 900 },
    createVad: async (scored, failed) => ({ push(frame) {
      if (++frames === 20) failed(new Error("Delayed worker"), [frame]);
      else scored(frame, frame[0] ? .95 : .01);
    }, reset() {}, dispose() {} }),
    onPhase: (phase) => phases.push(phase), onError: (error) => { throw error; },
    transcribe: async (audio) => {
      stt++; const bytes = await audio.arrayBuffer();
      const pcm = new Int16Array(bytes.slice(44));
      quietSamples = pcm.filter((value) => value > 100 && value < 400).length;
      return "Уайли, привет";
    },
    onTurn: async (_audio, _signal, phase, text) => {
      assert.equal(text, "Уайли, привет"); turns++; phase("thinking");
    },
  });
  try {
    await session.start();
    capture.push(25, .006); // 500 ms voice confirmed by Silero, below RMS threshold.
    capture.push(5, .05); // Only 100 ms loud: re-detecting loses the valid earlier speech.
    capture.push(60, 0);
    await tick();
  } finally { await session.stop(); }
  assert.equal(stt, 1, "fallback must not silently discard a VAD-confirmed utterance");
  assert.equal(turns, 1);
  assert.equal(quietSamples, 25 * 320, "the quiet wake-word onset must survive handover");
  assert.ok(phases.includes("transcribing") && phases.includes("thinking"));
});

class FakeWorker {
  static latest: FakeWorker;
  onmessage: ((event: { data: any }) => void) | null = null;
  onerror: ((event: any) => void) | null = null;
  closed = false;
  static respond = true;
  constructor(..._args: unknown[]) {
    FakeWorker.latest = this;
    queueMicrotask(() => this.onmessage?.({ data: { ready: true } }));
  }
  postMessage(data: any) {
    if (data.reset || !FakeWorker.respond) return;
    queueMicrotask(() => this.onmessage?.({ data: { id: data.id, epoch: data.epoch, score: .9, milliseconds: .1 } }));
  }
  terminate() { this.closed = true; }
}

test("a burst of buffered PCM is not mistaken for a 500 ms model deadline", async () => {
  const previous = globalThis.Worker;
  Object.assign(globalThis, { Worker: FakeWorker });
  let failures = 0, scores = 0;
  let vad: Awaited<ReturnType<typeof createLocalVad>> | undefined;
  try {
    vad = await createLocalVad(() => scores++, () => failures++);
    for (let i = 0; i < 35; i++) vad.push(new Float32Array(320));
    await tick();
  } finally { vad?.dispose(); Object.assign(globalThis, { Worker: previous }); }
  assert.equal(failures, 0, "700 ms buffered input delivered immediately is not 700 ms computation");
  assert.equal(scores, 21);
});

test("a genuinely stalled worker keeps its 500 ms deadline and transfers every pending PCM sample", async () => {
  const previous = globalThis.Worker; Object.assign(globalThis, { Worker: FakeWorker }); FakeWorker.respond = false;
  let reason = "", pending: Float32Array[] = [], calls = 0;
  let vad: Awaited<ReturnType<typeof createLocalVad>> | undefined;
  try {
    vad = await createLocalVad(() => {}, (error, samples) => { calls++; assert.ok(error instanceof VadFailure); reason = error.code; pending = samples; });
    vad.push(new Float32Array(640).fill(.006));
    await new Promise((resolve) => setTimeout(resolve, 550));
  } finally { vad?.dispose(); FakeWorker.respond = true; Object.assign(globalThis, { Worker: previous }); }
  assert.equal(calls, 1); assert.equal(reason, "worker_timeout");
  assert.equal(pending.reduce((sum, frame) => sum + frame.length, 0), 640);
});

test("PCM backlog remains bounded independently of the inference clock", async () => {
  const previous = globalThis.Worker; Object.assign(globalThis, { Worker: FakeWorker }); FakeWorker.respond = false;
  let failure: VadFailure | undefined;
  let vad: Awaited<ReturnType<typeof createLocalVad>> | undefined;
  try {
    vad = await createLocalVad(() => {}, (error) => { assert.ok(error instanceof VadFailure); failure = error; });
    for (let i = 0; i < 105; i++) vad.push(new Float32Array(320));
    assert.equal(failure?.code, "queue_overflow"); assert.equal(failure?.details.queueFrames, 65);
  } finally { vad?.dispose(); FakeWorker.respond = true; Object.assign(globalThis, { Worker: previous }); }
});

test("activation accepts safe leading punctuation and Russian variants, while music still rejects missing/incidental/quoted names", () => {
  for (const text of ["Уайли, привет", "Вайли, привет", "Майли, привет", "Wiley, привет", "… Уайли, привет", "— Уайли, привет", "Эй, Уайли, привет"]) {
    const decision = inspectActivation(text, "Уайли", true, true);
    assert.ok(decision.accepted, text); assert.equal(decision.command, "привет");
  }
  for (const text of ["Привет", "Мне нравится Уайли", '"Уайли, привет"', "Он сказал Уайли, привет"]) assert.equal(inspectActivation(text, "Уайли", true, true).accepted, false, text);
  assert.equal(inspectActivation("Привет", "Уайли", true, true).reason, "music_name_missing");
  assert.equal(inspectActivation("Уайли", "Уайли", true, true).reason, "name_only");
  assert.equal(inspectActivation("Привет", "Уайли", false).accepted, true);
});

const scenarios = [
  { name: "Silero normal", text: "Привет", music: false },
  { name: "Silero music + Smart complete", text: "Уайли, привет", music: true, smart: "complete" },
  { name: "Silero music + Smart incomplete", text: "Уайли, привет", music: true, smart: "incomplete" },
  { name: "Silero music + Smart unavailable", text: "Уайли, привет", music: true, smart: "missing" },
  { name: "Silero music + Smart error", text: "Уайли, привет", music: true, smart: "error" },
  { name: "Silero music + Smart deadline", text: "Уайли, привет", music: true, smart: "slow" },
  { name: "Worker error + RMS", text: "Уайли, привет", music: true, failure: true },
  { name: "manual RMS normal", text: "Привет", music: false, rms: true },
  { name: "manual RMS music", text: "Уайли, привет", music: true, rms: true },
  { name: "music rejects missing name", text: "Привет", music: true, rejected: true },
  { name: "empty STT", text: "", music: true, empty: true },
  { name: "failed STT", text: "Уайли, привет", music: true, sttError: true },
] as const;

for (const scenario of scenarios) test("full synthetic PCM → WAV → raw STT → activation → chat → response: " + scenario.name, async () => {
  const mode = scenario as { text: string; music: boolean; smart?: string; failure?: boolean; rms?: boolean; rejected?: boolean; empty?: boolean; sttError?: boolean };
  const file = await readFile("tests/fixtures/endpoint/short.wav");
  const pcm = new Float32Array((file.length - 44) / 2);
  for (let i = 0; i < pcm.length; i++) pcm[i] = file.readInt16LE(44 + i * 2) / 32768;
  const capture = new Capture(), chats: string[] = [], errors: unknown[] = [];
  let stt = 0, frames = 0, waited = false;
  const session = new Conversation({ capture, prepare: async () => {}, requireActivation: mode.music,
    cooldownMs: 0, onPhase: () => {}, onError: (error) => errors.push(error), onRecover: (error) => errors.push(error), sttEngine: "mock",
    speech: { threshold: .015, minimumSpeechMs: mode.music ? 300 : 160, silenceMs: 1000, noiseCalibrationMs: mode.music ? 600 : 0 },
    createVad: mode.rms ? undefined : async (scored, failed) => ({
      push(frame) {
        if (mode.failure && ++frames === 95) { failed(new VadFailure("worker_error", "Test worker"), [frame]); return; }
        const energy = Math.sqrt(frame.reduce((sum, n) => sum + n * n, 0) / frame.length);
        scored(frame, energy > .002 ? .95 : .01);
      }, reset() {}, dispose() {},
    }),
    smartTurn: !mode.smart ? undefined : async () => {
      if (mode.smart === "slow") return await new Promise(() => {});
      if (mode.smart === "error") throw new Error("Model error");
      return mode.smart === "missing" ? null : mode.smart === "complete";
    },
    activation: (text) => inspectActivation(text, "Уайли", mode.music, mode.music),
    transcribe: async (audio, signal) => {
      stt++; assert.equal(signal.aborted, false);
      const data = new DataView(await audio.arrayBuffer());
      assert.equal(data.getUint32(24, true), 16000); assert.equal(data.getUint16(22, true), 1);
      assert.ok(audio.size > 10000);
      if (mode.sttError) throw new TypeError("Server offline");
      return mode.text;
    },
    onTurn: async (_audio, signal, phase, text) => {
      assert.equal(signal.aborted, false);
      const command = activated(text!, "Уайли", mode.music)!;
      session.event("request_dispatched"); chats.push(command); phase("thinking"); phase("speaking");
    },
  });
  try {
    await session.start();
    for (let at = 0; at < pcm.length; at += 320) {
      capture.receive?.(pcm.slice(at, at + 320));
      const last = session.events.at(-1);
      if (!waited && mode.smart && last?.name === "smart_turn_started") {
        waited = true; await new Promise((resolve) => setTimeout(resolve, mode.smart === "slow" ? 375 : 5));
      }
    }
    await tick(); await tick();
    assert.equal(stt, 1, "each accepted speech segment reaches STT once");
    const names = session.events.map((event) => event.name);
    assert.ok(names.includes("utterance_finalized") && names.includes("stt_started"));
    if (mode.sttError) { assert.equal(errors.length, 1); assert.ok(names.includes("stt_failed")); }
    else if (mode.empty) { assert.ok(names.includes("stt_empty")); assert.equal(chats.length, 0); }
    else if (mode.rejected) { assert.equal(chats.length, 0); assert.ok(session.events.some((event) => event.name === "activation_rejected" && event.reason === "music_name_missing")); }
    else {
      assert.deepEqual(chats, [activated(mode.text, "Уайли", mode.music)]);
      assert.ok(names.includes("activation_accepted") && names.includes("request_dispatched") && names.includes("response_started"));
      assert.equal(session.phase, mode.music ? "awaiting" : "listening");
    }
  } finally { await session.stop(); }
});

test("diagnostic event history is bounded and never stores a transcript or waveform", () => {
  const trace = new VoiceTrace();
  for (let i = 0; i < 90; i++) trace.add("stt_completed", { characters: 20, reason: "private full text", text: "private full transcript", audio: [1, 2, 3] } as any);
  assert.equal(trace.events.length, 80);
  const json = JSON.stringify(trace.events);
  assert.ok(!json.includes("private") && !json.includes('"text"') && !json.includes('"audio"'));
});

test("segment reset completes WAV without aborting STT; two delayed recognitions return two replies", async () => {
  const capture = new Capture(); let count = 0; const replies: string[] = []; const signals: AbortSignal[] = [];
  let resolve: (value: string) => void = () => {};
  const session = new Conversation({ capture, cooldownMs: 0, prepare: async () => {}, onPhase: () => {}, onError: (error) => { throw error; },
    createVad: async (scored) => ({ push(frame) { scored(frame, frame[0] ? .95 : .01); }, reset() {}, dispose() {} }),
    transcribe: async (_audio, signal) => { count++; signals.push(signal); return await new Promise((done) => { resolve = done; }); },
    activation: (text) => inspectActivation(text, "Уайли", true),
    onTurn: async (_audio, _signal, phase, text) => { replies.push(text!); phase("speaking"); },
  });
  try {
    await session.start();
    for (let i = 0; i < 2; i++) {
      capture.push(25, .1); capture.push(60, 0); await tick();
      assert.equal(count, i + 1); assert.equal(signals[i].aborted, false);
      capture.push(60, 0); await tick(); assert.equal(signals[i].aborted, false);
      resolve("Уайли, привет " + i); await tick(); await tick();
      assert.equal(session.phase, "listening");
    }
    assert.deepEqual(replies, ["Уайли, привет 0", "Уайли, привет 1"]);
  } finally { await session.stop(); }
});

test("cancelling STT ignores a late successful transcript and releases the microphone", async () => {
  const capture = new Capture(); let dispatches = 0, calls = 0, signal: AbortSignal | undefined;
  let resolve: (value: string) => void = () => {};
  const session = new Conversation({ capture, prepare: async () => {}, onPhase: () => {}, onError: (error) => { throw error; },
    transcribe: async (_audio, current) => { calls++; signal = current; return await new Promise((done) => { resolve = done; }); },
    onTurn: async () => { dispatches++; },
  });
  await session.start(); capture.push(25, .1); capture.push(60, 0); await tick();
  await session.stop(); resolve("Открой приложение"); await tick();
  assert.equal(calls, 1); assert.equal(signal?.aborted, true); assert.equal(dispatches, 0); assert.equal(capture.receive, null);
  assert.ok(session.events.some((event) => event.name === "request_cancelled"));
  assert.ok(!session.events.some((event) => event.name === "activation_accepted"));
});

test("stopping Smart Turn cancels its timer and never emits a misleading later timeout or phrase", async () => {
  const events: string[] = []; let results = 0;
  const endpoint = new EndpointDetector(16000, {}, async () => await new Promise(() => {}), () => results++, (name) => events.push(name));
  for (let i = 0; i < 25; i++) endpoint.push(new Float32Array(320).fill(.1), .95);
  for (let i = 0; i < 26; i++) endpoint.push(new Float32Array(320), .01);
  assert.ok(events.includes("smart_turn_started")); endpoint.reset();
  await new Promise((resolve) => setTimeout(resolve, 380));
  assert.equal(results, 0); assert.ok(events.includes("smart_turn_cancelled"));
  assert.ok(!events.includes("smart_turn_timeout") && !events.includes("smart_turn_completed"));
});

test("a worker error from a retired epoch cannot switch a new phrase to RMS", async () => {
  const previous = globalThis.Worker;
  Object.assign(globalThis, { Worker: FakeWorker });
  let failures = 0;
  let vad: Awaited<ReturnType<typeof createLocalVad>> | undefined;
  try {
    vad = await createLocalVad(() => {}, () => failures++);
    vad.reset();
    FakeWorker.latest.onmessage?.({ data: { error: "retired inference", epoch: 0, id: 1 } });
    await tick();
  } finally { vad?.dispose(); Object.assign(globalThis, { Worker: previous }); }
  assert.equal(failures, 0);
});
