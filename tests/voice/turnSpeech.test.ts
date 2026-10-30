import test from "node:test";
import assert from "node:assert/strict";
import { SpeechOutput } from "../../src/voice/output.ts";
import { TurnSpeech } from "../../src/voice/turnSpeech.ts";

function route(mode: "brief" | "full" | "off") {
  const controller = new AbortController(), synthesized: string[] = [], played: string[] = [];
  const router = new TurnSpeech<string>(mode, () => new SpeechOutput<string>(async (text) => { synthesized.push(text); return text; }, async (_, __, text) => { played.push(text); }, controller.signal), controller.signal);
  return { router, controller, synthesized, played };
}
test("action diagnostics stay in the display and reach TTS only as the structured phrase", async () => {
  const { router, synthesized } = route("brief");
  router.event({ type: "speech_mode", mode: "action" });
  router.event({ type: "delta", text: "Процесс подтверждён. PID 123. C:\\secret\\app.exe." });
  router.event({ type: "speech_result", action: { spoken: "Процесс Blender запущен." } });
  router.finish("Процесс подтверждён. PID 123. C:\\secret\\app.exe.");
  await router.done;
  assert.deepEqual(synthesized, ["Процесс Blender запущен."]);
});
test("full mode reads display once, and off suppresses only actions", async () => {
  const full = route("full"); full.router.event({ type: "speech_mode", mode: "action" }); full.router.event({ type: "delta", text: "Готово. " }); full.router.event({ type: "speech_result", action: { spoken: "Другое." } }); full.router.finish("Готово. "); await full.router.done; assert.deepEqual(full.synthesized, ["Готово."]);
  const off = route("off"); off.router.event({ type: "speech_mode", mode: "action" }); off.router.event({ type: "delta", text: "Данные." }); off.router.event({ type: "speech_result", action: { spoken: "Готово." } }); off.router.finish("Данные."); await off.router.done; assert.deepEqual(off.synthesized, []);
  const chat = route("off"); chat.router.event({ type: "delta", text: "Полный ответ. " }); chat.router.finish("Полный ответ. "); await chat.router.done; assert.deepEqual(chat.synthesized, ["Полный ответ."]);
});
test("aborted or cancelled turns cannot start late speech", async () => {
  const { router, controller, synthesized } = route("brief");
  router.event({ type: "speech_mode", mode: "action" }); controller.abort();
  router.event({ type: "speech_result", action: { spoken: "Запускаю." } }); router.finish("доклад");
  assert.deepEqual(synthesized, []);
});
test("explicit full reading overrides the action-speech preference", async () => {
  const { router, synthesized } = route("off");
  router.event({ type: "speech_mode", mode: "read_full" });
  router.event({ type: "speech_result", action: { spoken: "Полный ответ. PID 123." } });
  router.event({ type: "delta", text: "Читаю предыдущий ответ." });
  router.finish("Читаю предыдущий ответ."); await router.done;
  assert.equal(synthesized.join(" "), "Полный ответ. PID 123.");
});
test("interrupt during TTS cancels playback and never plays a late result", async () => {
  const controller = new AbortController(), played: string[] = [];
  let resolveAudio: (value: string) => void = () => {};
  const router = new TurnSpeech<string>("brief", () => new SpeechOutput<string>(
    () => new Promise((resolve) => { resolveAudio = resolve; }),
    async (value) => { played.push(value); }, controller.signal,
  ), controller.signal);
  router.event({ type: "speech_mode", mode: "action" });
  router.event({ type: "speech_result", action: { spoken: "Процесс запущен." } });
  router.finish("PID 123");
  await new Promise((resolve) => setTimeout(resolve, 0));
  controller.abort(); resolveAudio("late audio");
  await assert.rejects(router.done!);
  assert.deepEqual(played, []);
});
test("dispatch is spoken immediately without repeating the confirmed outcome", async () => {
  const { router, synthesized } = route("brief");
  router.event({ type: "speech_mode", mode: "action" });
  router.event({ type: "speech_start", text: "Запускаю Blender." });
  router.event({ type: "delta", text: "PID 123 и путь." });
  router.event({ type: "speech_result", action: { status: "process_started", spoken: "Процесс Blender запущен." } });
  router.finish("PID 123 и путь."); await router.done;
  assert.deepEqual(synthesized, ["Запускаю Blender."]);
});
test("a failure after dispatch produces a short follow-up", async () => {
  const { router, synthesized } = route("brief");
  router.event({ type: "speech_mode", mode: "action" });
  router.event({ type: "speech_start", text: "Запускаю Blender." });
  router.event({ type: "speech_result", action: { status: "error", spoken: "Не удалось открыть Blender." } });
  router.finish("Техническая ошибка."); await router.done;
  assert.deepEqual(synthesized, ["Запускаю Blender.", "Не удалось открыть Blender."]);
});
