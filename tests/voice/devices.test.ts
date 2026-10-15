import test from "node:test";
import assert from "node:assert/strict";
import {
  microphoneConstraints,
  playAudio,
  selectOutput,
} from "../../src/voice/devices.ts";

test("selected microphone is required exactly; the Windows default omits its ID", () => {
  assert.deepEqual(
    (microphoneConstraints("usb-mic").audio as MediaTrackConstraints).deviceId,
    { exact: "usb-mic" },
  );
  assert.equal(
    (microphoneConstraints().audio as MediaTrackConstraints).deviceId,
    undefined,
  );
});

test("missing output reports an error instead of silently playing on another device", async () => {
  const ids: string[] = [];
  const audio = {
    setSinkId: async (id: string) => {
      ids.push(id);
      throw new Error("Missing");
    },
  };
  await assert.rejects(
    selectOutput(audio as HTMLMediaElement, "unplugged-headphones"),
    /динамик недоступен/,
  );
  assert.deepEqual(ids, ["unplugged-headphones"]);
});

test("cancelling while selecting the speaker never starts playback", async () => {
  const previous = globalThis.Audio;
  let selected: () => void = () => {};
  let plays = 0;
  class Audio {
    async setSinkId() {
      await new Promise<void>((resolve) => {
        selected = resolve;
      });
    }
    play() {
      plays++;
      return Promise.resolve();
    }
    pause() {}
    removeAttribute() {}
    load() {}
  }
  Object.assign(globalThis, { Audio });
  try {
    const controller = new AbortController();
    const playback = playAudio(
      new Blob(["audio"]),
      "headphones",
      controller.signal,
    );
    controller.abort();
    selected();
    await assert.rejects(playback, { name: "AbortError" });
    assert.equal(plays, 0);
  } finally {
    Object.assign(globalThis, { Audio: previous });
  }
});

test("cancelling playback releases the audio source and event handlers", async () => {
  const previous = globalThis.Audio;
  let current: Audio;
  class Audio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    removed = false;
    pauses = 0;
    constructor() {
      current = this;
    }
    async setSinkId(id: string) {
      assert.equal(id, "headphones");
    }
    async play() {}
    pause() {
      this.pauses++;
    }
    removeAttribute(name: string) {
      assert.equal(name, "src");
      this.removed = true;
    }
    load() {}
  }
  Object.assign(globalThis, { Audio });
  try {
    const controller = new AbortController();
    const playback = playAudio(
      new Blob(["audio"]),
      "headphones",
      controller.signal,
    );
    await new Promise((resolve) => setImmediate(resolve));
    controller.abort();
    await assert.rejects(playback, { name: "AbortError" });
    assert.equal(current!.removed, true);
    assert.ok(current!.pauses > 0);
    assert.equal(current!.onended, null);
    assert.equal(current!.onerror, null);
  } finally {
    Object.assign(globalThis, { Audio: previous });
  }
});
