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
