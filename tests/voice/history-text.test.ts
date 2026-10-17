import test from "node:test";
import assert from "node:assert/strict";
import { historyParts } from "../../src/historyText.ts";

test("history highlight preserves full text, Russian prefixes, ё and literal markup", () => {
  const text =
    "Проектирование, ёжик, ЕЖИКА. <img onerror=example> и СОКОЛ-7351.";
  const parts = historyParts(text, ["проект", "ежик", "7351"]);
  assert.equal(parts.map((part) => part.text).join(""), text);
  assert.deepEqual(
    parts.filter((part) => part.match).map((part) => part.text),
    ["Проектирование", "ёжик", "ЕЖИКА", "7351"],
  );
  assert.equal(
    historyParts("предпроектный", ["проект"]).some((part) => part.match),
    false,
  );
  assert.deepEqual(historyParts(text, [".*", "[bad]"]), [
    { text, match: false },
  ]);
});
test("history highlight bounds DOM spans without dropping the rest of a long answer", () => {
  const text = "Найденное слово. ".repeat(10000);
  const parts = historyParts(text, ["найден"]);
  assert.equal(parts.filter((part) => part.match).length, 80);
  assert.equal(parts.map((part) => part.text).join(""), text);
});
