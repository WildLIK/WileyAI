import { test } from "node:test";
import assert from "node:assert/strict";
import { playAudio } from "../../src/voice/devices.ts";

test("mouth playback signal waits for real media start and ignores a late cancelled start", async () => {
  const previous = globalThis.Audio;
  let current: Audio,
    started = 0;
  class Audio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ready!: () => void;
    constructor() {
      current = this;
    }
    async setSinkId() {}
    play() {
      return new Promise<void>((resolve) => {
        this.ready = resolve;
      });
    }
    pause() {}
    removeAttribute() {}
    load() {}
  }
  Object.assign(globalThis, { Audio });
  try {
    const signal = new AbortController();
    const pending = playAudio(new Blob(["audio"]), "", signal.signal, () => {
      started++;
    });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(started, 0);
    current!.ready();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(started, 1);
    current!.onended!();
    await pending;
    const cancelled = new AbortController();
    const late = playAudio(new Blob(["audio"]), "", cancelled.signal, () => {
      started++;
    });
    await new Promise((resolve) => setImmediate(resolve));
    cancelled.abort();
    await assert.rejects(late, { name: "AbortError" });
    current!.ready();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(started, 1);
  } finally {
    Object.assign(globalThis, { Audio: previous });
  }
});
