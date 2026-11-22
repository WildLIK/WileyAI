const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const crypto = require("node:crypto");

test("bundled VAD matches its pinned artifact and the installer carries model/runtime licenses", () => {
  const manifest = JSON.parse(fs.readFileSync("assets/voice/manifest.json", "utf8"));
  const bytes = fs.readFileSync("assets/voice/silero_vad_v5.onnx");
  assert.equal(bytes.length, manifest["silero_vad_v5.onnx"].bytes);
  assert.equal(crypto.createHash("sha256").update(bytes).digest("hex"), manifest["silero_vad_v5.onnx"].sha256);
  const packaging = fs.readFileSync("electron-builder.yml", "utf8");
  assert.match(packaging, /from: assets\/voice/);
  assert.match(fs.readFileSync("assets/voice/ONNX-Runtime-LICENSE.txt", "utf8"), /MIT License/);
  assert.match(fs.readFileSync("assets/voice/Smart-Turn-LICENSE.txt", "utf8"), /BSD 2-Clause/);
});
