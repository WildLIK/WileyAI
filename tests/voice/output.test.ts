import test from "node:test";
import assert from "node:assert/strict";
import { SpeechOutput, SpeechText } from "../../src/voice/output.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));
test("speech starts with a complete sentence and keeps decimals and incomplete words", () => {
  const text = new SpeechText();
  assert.deepEqual(text.push("Цена 3.5 руб. за штуку. Ещё"), [
    "Цена 3.5 руб. за штуку.",
  ]);
  assert.deepEqual(text.push(" одно слово"), []);
  assert.deepEqual(text.finish("Цена 3.5 руб. за штуку. Ещё одно слово!"), [
    "Ещё одно слово!",
  ]);
  assert.deepEqual(new SpeechText().finish("Ответ локальной команды."), [
    "Ответ локальной команды.",
  ]);
});
test("bounds a long sentence and discards markup-only pieces", () => {
  const text = new SpeechText();
  const chunks = [
    ...text.push("***\n" + "длинное слово ".repeat(100)),
    ...text.finish(),
  ];
  assert.ok(chunks.length > 1);
  assert.ok(
    chunks.every((chunk) => chunk.length <= 240 && /[а-я]/.test(chunk)),
  );
});

test("cloud joins a tiny acknowledgement to the reply and bounds the first audio and following batches", async () => {
  const rendered: string[] = [];
  const output = new SpeechOutput(
    async (text) => {
      rendered.push(text);
      return text;
    },
    async () => {},
    undefined,
    {
      batchCharacters: 300,
      firstCharacters: 180,
      firstMinimum: 24,
      firstWaitMs: 200,
    },
  );
  output.push("Поняла. ");
  await tick();
  assert.deepEqual(rendered, []);
  const rest =
    "Сейчас подробно расскажу о голосе персонажа и настройке программы, чтобы разговор звучал естественно. "
      .repeat(20)
      .trim();
  output.push(rest + " ");
  await tick();
  assert.ok(rendered[0].startsWith("Поняла. Сейчас подробно"));
  assert.ok(rendered[0].length <= 180);
  output.finish();
  await output.done;
  assert.ok(rendered.every((text) => text.length <= 300));
  assert.equal(rendered.join(" "), "Поняла. " + rest);
});

test("cloud acknowledgement wait is bounded and immediately cancellable", async () => {
  let rendered = 0;
  const output = new SpeechOutput(
    async (text) => {
      rendered++;
      return text;
    },
    async () => {},
    undefined,
    {
      batchCharacters: 300,
      firstCharacters: 180,
      firstMinimum: 24,
      firstWaitMs: 200,
    },
  );
  output.push("Поняла. ");
  await tick();
  output.cancel();
  await assert.rejects(output.done, { name: "AbortError" });
  assert.equal(rendered, 0);
  const short = new SpeechOutput(
    async (text) => {
      rendered++;
      return text;
    },
    async () => {},
    undefined,
    { batchCharacters: 300, firstMinimum: 24, firstWaitMs: 10 },
  );
  short.push("Поняла. ");
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(rendered, 1);
  short.finish();
  await short.done;
});
test("plays before text completion, prefetches only one segment, preserves order", async () => {
  const rendered: string[] = [],
    played: string[] = [];
  let release!: () => void;
  const firstPlayback = new Promise<void>((resolve) => {
    release = resolve;
  });
  const output = new SpeechOutput(
    async (text) => {
      rendered.push(text);
      return text;
    },
    async (text) => {
      played.push(text);
      if (played.length === 1) await firstPlayback;
    },
  );
  output.push("Первая фраза. Вторая фраза. Третья фраза. ");
  await tick();
  assert.deepEqual(rendered, ["Первая фраза.", "Вторая фраза."]);
  assert.deepEqual(played, ["Первая фраза."]);
  release();
  output.finish();
  await output.done;
  assert.deepEqual(played, ["Первая фраза.", "Вторая фраза.", "Третья фраза."]);
});
test("interrupt discards queued and later text while waiting for the model", async () => {
  const played: string[] = [];
  const output = new SpeechOutput(
    async (text) => text,
    async (text) => {
      played.push(text);
    },
  );
  output.push("Первая фраза. ");
  await tick();
  output.controller.abort(); // The same controller is exposed to the app's Stop and Escape.
  await assert.rejects(output.done, { name: "AbortError" });
  output.push("Не произносить. ");
  output.finish("Не произносить.");
  assert.deepEqual(played, ["Первая фраза."]);
});
test("synthesis and playback failures stop prefetch and remain visible", async () => {
  const output = new SpeechOutput(
    async (text) => text,
    async () => {
      throw new Error("Нет динамика");
    },
  );
  output.push("Первая фраза. Вторая фраза. ");
  await assert.rejects(output.done, /Нет динамика/);
});

test("model/API batching coalesces a ready backlog without delaying the first phrase", async () => {
  const rendered: string[] = [],
    played: string[] = [];
  let release!: () => void;
  const first = new Promise<void>((resolve) => {
    release = resolve;
  });
  const output = new SpeechOutput(
    async (text) => {
      rendered.push(text);
      if (rendered.length === 1) await first;
      return text;
    },
    async (text) => {
      played.push(text);
    },
    undefined,
    { batchCharacters: 240 },
  );
  output.push("Первая фраза. ");
  await tick();
  assert.deepEqual(rendered, ["Первая фраза."]);
  output.push("Вторая фраза. Третья фраза. ");
  output.finish();
  release();
  await output.done;
  assert.deepEqual(rendered, ["Первая фраза.", "Вторая фраза. Третья фраза."]);
  assert.deepEqual(played, rendered);
});
