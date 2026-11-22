import test from "node:test";
import assert from "node:assert/strict";
import { Conversation } from "../../src/voice/conversation.ts";

class Capture {
  sampleRate = 16000;
  starts = 0; stops = 0;
  receive: ((frame: Float32Array) => void) | null = null;
  async start(receive: (frame: Float32Array) => void) { this.starts++; this.receive = receive; }
  async stop() { this.stops++; this.receive = null; }
  phrase() { for (let n=0;n<25;n++) this.receive?.(new Float32Array(320).fill(.1)); for (let n=0;n<55;n++) this.receive?.(new Float32Array(320)); }
}
const tick = () => new Promise(resolve => setTimeout(resolve, 10));

for (const failure of ["tool", "network", "tts429", "none"]) test(`three sequential turns retain one microphone lease after ${failure}`, async () => {
  const capture = new Capture(); let turns = 0; let release = () => {}; const recovered: unknown[] = [];
  const options = { capture, queueMode: "sequential" as const, listenWhileThinking: true, cooldownMs: 0,
    prepare: async () => {}, onPhase: () => {}, onError: (error: unknown) => { throw error; }, onRecover: (error: unknown) => recovered.push(error),
    transcribe: async () => "Команда",
    onTurn: async (_audio: Blob, _signal: AbortSignal, phase: (value: any) => void) => {
      turns++; phase("executing");
      if (turns === 1) {
        await new Promise<void>(resolve => { release = resolve; });
        if (failure !== "none") throw new Error(failure === "tts429" ? "HTTP 429" : failure);
      }
    },
  };
  const session = new Conversation(options);
  try {
    await session.start(); capture.phrase(); await tick();
    capture.phrase(); await tick(); assert.equal(turns, 1, "ordinary busy input is discarded");
    release(); await tick();
    assert.equal(session.active, true); assert.equal(session.phase, "listening");
    capture.phrase(); await tick(); capture.phrase(); await tick();
    assert.equal(turns, 3); assert.equal(capture.starts, 1); assert.equal(capture.stops, 0);
    assert.equal(recovered.length, failure === "none" ? 0 : 1);
    await session.stop(); capture.phrase(); await tick(); assert.equal(turns, 3); assert.equal(capture.stops, 1);
  } finally { release(); await session.stop(); }
});
