import test from "node:test";
import assert from "node:assert/strict";
import { activated, playbackEcho } from "../../src/voice/activation.ts";

test("activation only at the beginning; preserves song spelling and rejects quoted/incidental names", () => {
  assert.equal(
    activated("Уайли, найди Linkin Park With You", "Уайли"),
    "найди Linkin Park With You",
  );
  assert.equal(activated("Она сказала Уайли пауза", "Уайли"), null);
  assert.equal(activated("Уайли", "Уайли"), null);
  assert.equal(activated("Уайли,пауза", "Уайли"), "пауза");
  assert.equal(activated("«Уайли, пауза»", "Уайли"), null);
  assert.equal(activated("Пауза", "Уайли", false), "Пауза");
  assert.equal(
    playbackEcho(
      "Уайли, поставь на паузу",
      "Скажите: Уайли, поставь на паузу.",
    ),
    true,
  );
  assert.equal(
    playbackEcho("Уайли, найди Linkin Park", "Погода завтра прохладная"),
    false,
  );
});

test("a misheard name still addresses her, and is removed before the command", () => {
  // Real Whisper small outputs for «Уайли, …» from the synthetic bench.
  for (const heard of [
    "Майли",
    "Уали",
    "Вайли",
    "Вейли",
    "Уэйли",
    "Wiley",
    "Wylie",
  ])
    assert.equal(
      activated(`${heard}, какая завтра погода?`, "Уайли"),
      "какая завтра погода?",
      heard,
    );
  assert.equal(
    activated("Уайли. Открой Telegram.", "Уайли"),
    "Открой Telegram.",
  );
  assert.equal(activated("Эй, Уайли, пауза", "Уайли"), "пауза");
  assert.equal(
    activated("Майли, прибавь громкость на десять.", "Уайли", false),
    "прибавь громкость на десять.",
  );
  assert.equal(activated("Уайли.", "Уайли", false), "Уайли.");
  // Ordinary first words are not the name.
  for (const phrase of [
    "Ладно, пауза",
    "Майки купить",
    "Давай дальше",
    "Знаешь что",
    "Али, привет",
  ])
    assert.equal(activated(phrase, "Уайли"), null, phrase);
  assert.equal(activated("Ладно, пауза", "Уайли", false), "Ладно, пауза");
  assert.equal(activated("Эй ты, пауза", "Уайли"), null);
});
