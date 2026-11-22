// Packaged runtime/ONNX integration check. No owner profile, microphone or model download.
import { _electron as electron, expect } from "@playwright/test";
import { mkdir, mkdtemp, readFile, readdir } from "node:fs/promises";
import { resolve, join } from "node:path";

const executablePath = resolve("local/releases/win-unpacked/WileyAI.exe");
const base = resolve("local/review/voice33-packaged");
await mkdir(base, { recursive: true });
const profile = await mkdtemp(join(base, "profile-"));
const env = { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: profile, PATH: join(process.env.SystemRoot, "System32"), TEMP: profile, TMP: profile };
for (const key of ["WILEYAI_PYTHON", "WILEYAI_DEV", "PYTHONPATH", "NODE_OPTIONS"]) delete env[key];
const launch = async () => {
  const app = await electron.launch({ executablePath, cwd: profile, args: ["--mute-audio"], env });
  app.process().stderr.on("data", (data) => process.stderr.write(data));
  return app;
};
const close = async (app) => {
  const timer = setTimeout(() => app.process().kill(), 5000);
  try { await app.close(); } finally { clearTimeout(timer); }
};
let app = await launch();
try {
  const page = await app.firstWindow();
  await page.getByRole("heading", { name: "Давайте познакомимся" }).waitFor();
  await page.getByRole("button", { name: "Настроить позже", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
  const connection = await page.evaluate(() => window.wiley.connection());
  const api = async (path, method = "GET", body) => {
    const response = await fetch(connection.url + path, { method, headers: { Authorization: "Bearer " + connection.token, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    if (!response.ok) throw new Error(path + ": HTTP " + response.status);
    return response.json();
  };
  const settings = await api("/settings"), status = await api("/voice/endpoint/status");
  if (settings.conversation_vad !== "auto" || settings.conversation_endpoint_mode !== "auto" || settings.conversation_smart_turn || status.installed || status.available) throw new Error("Optional endpoint runtime/model is not isolated in the base package");
  const licenses = await readdir(resolve("local/releases/win-unpacked/resources/licenses/voice"));
  for (const file of ["ONNX-Runtime-LICENSE.txt", "ONNX-Runtime-ThirdPartyNotices.txt", "Smart-Turn-LICENSE.txt", "manifest.json"]) if (!licenses.includes(file)) throw new Error("Missing packaged license: " + file);
  if (!(await readFile(resolve("local/releases/win-unpacked/resources/backend/requirements/endpoint.txt"), "utf8")).includes("onnxruntime==")) throw new Error("Missing optional component requirements");
  const worker = (await readdir("dist/assets")).find((file) => /^vad-worker-.*\.js$/.test(file));
  if (!worker) throw new Error("Build the frontend first");
  const wav = await readFile("tests/fixtures/endpoint/short.wav");
  const samples = Array.from({ length: (wav.length - 44) / 2 }, (_, i) => wav.readInt16LE(44 + i * 2) / 32768);
  await page.context().setOffline(true);
  const result = await page.evaluate(({ worker, samples }) => new Promise((resolve, reject) => {
    const engine = new Worker("app://wileyai/assets/" + worker, { type: "module" }), scores = [];
    let count = 0;
    const finish = (error) => { clearTimeout(timer); engine.terminate(); error ? reject(new Error(error)) : resolve({ frames: scores.length, voice: scores.some((score) => score > .8), quiet: scores.slice(-40).every((score) => score < .1) }); };
    const timer = setTimeout(() => finish("Packaged VAD timed out"), 15000);
    engine.onerror = (error) => finish(error.message);
    engine.onmessage = ({ data }) => {
      if (data.error) { finish(data.error); return; }
      if (data.ready) {
        for (let at = 0; at < samples.length; at += 512) {
          const audio = new Float32Array(512); audio.set(samples.slice(at, at + 512)); engine.postMessage({ id: ++count, epoch: 0, audio });
        }
      } else { scores.push(data.score); if (scores.length === count) finish(); }
    };
  }), { worker, samples });
  if (!result.voice || !result.quiet) throw new Error("Packaged VAD did not distinguish synthetic Russian speech and silence");
  await page.context().setOffline(false);
  await api("/settings", "PUT", { ...settings, conversation_endpoint_mode: "dictation", conversation_vad: "rms", conversation_smart_turn: true });
  await close(app); app = await launch();
  const next = await app.firstWindow();
  await expect(next.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
  const saved = await next.evaluate(async () => {
    const connection = await window.wiley.connection();
    const headers = { Authorization: "Bearer " + connection.token };
    const [settings, status] = await Promise.all(["/settings", "/voice/endpoint/status"].map(async (path) => (await fetch(connection.url + path, { headers })).json()));
    return { mode: settings.conversation_endpoint_mode, vad: settings.conversation_vad, smart: settings.conversation_smart_turn, installed: status.installed };
  });
  if (saved.mode !== "dictation" || saved.vad !== "rms" || !saved.smart || saved.installed) throw new Error("Packaged restart failed or implicitly installed optional weights");
  console.log(JSON.stringify({ packagedEndpoint: "passed", offlineSilero: result, restart: saved, portablePython: true, microphoneOpened: false, installerExecuted: false }));
} finally { await close(app); }
