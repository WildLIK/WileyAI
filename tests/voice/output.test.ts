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
