import test from "node:test";
import assert from "node:assert/strict";
import { AvatarMusic } from "../../src/avatarMusic.ts";

// Real SSE parsing/lease lifetime; no player or user's settings needed.
test("stalled transport, duplicate, stale and delayed frames cannot revive music", async (t) => {
  let now = 0,
    connection = 0;
  const send: Array<(d: object) => void> = [];
  const sources: AbortSignal[] = [];
  const fixture = {
    type: "music",
    observation: "sample",
    revision: 5,
    active: true,
    source: "fixture",
    level: 0.6,
    beat: 0.5,
    phase: 1,
    fresh_ms: 1000,
  };
  const tick = () => new Promise<void>((r) => setImmediate(r));
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      wiley: {
        connection: async () => ({ url: "http://local", token: "fixture" }),
      },
    },
  });
  t.after(() => Reflect.deleteProperty(globalThis, "window"));
  t.mock.method(globalThis, "fetch", async (_: unknown, init: RequestInit) => {
    connection++;
    sources.push(init.signal!);
    return new Response(
      new ReadableStream({
        start(c) {
          send.push((d) =>
            c.enqueue(
              new TextEncoder().encode("data: " + JSON.stringify(d) + "\n\n"),
            ),
          );
        },
      }),
    );
  });
  const m = new AvatarMusic(() => now);
  t.after(() => m.setEnabled(false));
  m.setEnabled(true);
  m.setEnabled(true);
  await tick();
  assert.equal(connection, 1);
  send[0](fixture);
  await tick();
  assert.ok(m.value.active);
  now = 750;
  send[0](fixture);
  await tick();
  now = 1000;
  assert.equal(m.value.active, false);
  assert.match(m.value.error, /устарели/);
  send[0]({ ...fixture, revision: 6 });
  await tick();
  assert.ok(m.value.active);
  send[0]({ ...fixture, revision: 4, observation: "error" });
  await tick();
  assert.ok(m.value.active);
  send[0]({ ...fixture, revision: 6, observation: "stale" });
  await tick();
  assert.equal(m.value.active, false);
  m.setEnabled(false);
  assert.ok(sources[0].aborted);
  m.setEnabled(true);
  await tick();
  send[0]({ ...fixture, revision: 7 });
  await tick();
  assert.equal(m.value.active, false);
  send[1]({ ...fixture, revision: 1 });
  await tick();
  assert.ok(m.value.active);
  m.setEnabled(false);
  assert.equal(m.value.error, "");
});

test("a quiet connection is reopened once and hiding cancels further retries", async (t) => {
  let now = 0;
  const signals: AbortSignal[] = [];
  const tick = () => new Promise<void>((r) => setImmediate(r));
  t.mock.timers.enable({ apis: ["setInterval", "setTimeout"] });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      wiley: {
        connection: async () => ({ url: "http://local", token: "fixture" }),
      },
    },
  });
  t.after(() => Reflect.deleteProperty(globalThis, "window"));
  t.mock.method(globalThis, "fetch", async (_: unknown, init: RequestInit) => {
    const signal = init.signal!;
    signals.push(signal);
    return new Response(
      new ReadableStream({
        start(c) {
          signal.addEventListener(
            "abort",
            () => c.error(new Error("aborted")),
            { once: true },
          );
        },
      }),
    );
  });
  const music = new AvatarMusic(() => now);
  t.after(() => music.setEnabled(false));
  music.setEnabled(true);
  await tick();
  now = 3000;
  t.mock.timers.tick(3000);
  await tick();
  assert.equal(signals.length, 1);
  assert.ok(signals[0].aborted);
  now += 2000;
  t.mock.timers.tick(2000);
  await tick();
  assert.equal(signals.length, 2);
  assert.ok(!signals[1].aborted);
  music.setEnabled(false);
  await tick();
  now += 6000;
  t.mock.timers.tick(6000);
  await tick();
  assert.equal(signals.length, 2);
  assert.ok(signals[1].aborted);
  assert.equal(music.value.error, "");
});
