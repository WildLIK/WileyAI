import test from "node:test";
import assert from "node:assert/strict";
import { fishVoiceId, MITA_VOICE } from "../../src/voice/fish.ts";

test("Fish accepts the Mita voice page and share links, without changing other voice IDs", () => {
  for (const prefix of [
    "https://fish.audio/ru/m/",
    "https://fish.audio/m/",
    "https://www.fish.audio/app/m/",
  ])
    assert.equal(
      fishVoiceId(prefix + MITA_VOICE + "/?share=1#sample"),
      MITA_VOICE,
    );
  assert.equal(fishVoiceId(" " + MITA_VOICE + " "), MITA_VOICE);
  assert.equal(fishVoiceId(""), "");
  assert.equal(fishVoiceId("custom-speaker"), "custom-speaker");
  for (const url of [
    "https://fish.audio.evil.org/m/" + MITA_VOICE,
    "https://user:pass@fish.audio/m/" + MITA_VOICE,
    "http://fish.audio/m/" + MITA_VOICE,
    "https://fish.audio/m/not-an-id",
    "https://fish.audio/",
  ])
    assert.throws(() => fishVoiceId(url), /ссылку/);
});
