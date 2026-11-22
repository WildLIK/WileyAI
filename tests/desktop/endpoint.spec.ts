import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, readdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { wav } from "../../src/voice/speech";

test("bundled Silero worker runs on the Electron app origin offline and rejects silence", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-neural-vad-"));
  const app = await electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  try {
    const page = await app.firstWindow(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    const worker = (await readdir("dist/assets")).find((path) => /^vad-worker-.*\.js$/.test(path))!;
    const input = await readFile("tests/fixtures/endpoint/short.wav");
    const samples = [...new Int16Array(input.buffer.slice(input.byteOffset + 44, input.byteOffset + input.length))].map((v) => v / 32768);
    const before = await app.evaluate(({ app }) => app.getAppMetrics().filter((row) => row.type === "Tab").map((row) => ({ cpu: row.cpu.cumulativeCPUUsage, memory: row.memory.workingSetSize })));
    await page.context().setOffline(true);
    const result = await page.evaluate(async ({ worker, samples }) => {
      return await new Promise<{ scores: number[]; milliseconds: number }>((resolve, reject) => {
        const began = performance.now(), engine = new Worker("app://wileyai/assets/" + worker, { type: "module" });
        const scores: number[] = []; let count = 0;
        const timer = setTimeout(() => { engine.terminate(); reject(new Error("Bundled VAD timed out")); }, 15000);
        engine.onerror = (error) => { clearTimeout(timer); engine.terminate(); reject(new Error(error.message)); };
        engine.onmessage = ({ data }) => {
          if (data.error) { clearTimeout(timer); engine.terminate(); reject(new Error(data.error)); return; }
          if (data.ready) {
            for (let at = 0; at < samples.length; at += 512) {
              const frame = new Float32Array(512); frame.set(samples.slice(at, at + 512)); engine.postMessage({ id: ++count, epoch: 0, audio: frame });
            }
          } else {
            scores.push(data.score);
            if (scores.length === count) { clearTimeout(timer); engine.terminate(); resolve({ scores, milliseconds: performance.now() - began }); }
          }
        };
      });
    }, { worker, samples });
    expect(result.scores.some((value) => value > .8)).toBe(true);
    expect(result.scores.slice(-40).every((value) => value < .1)).toBe(true);
    const after = await app.evaluate(({ app }) => app.getAppMetrics().filter((row) => row.type === "Tab").map((row) => ({ cpu: row.cpu.cumulativeCPUUsage, memory: row.memory.workingSetSize, peak: row.memory.peakWorkingSetSize })));
    console.log("Bundled Silero CPU/WASM: " + JSON.stringify({ frames: result.scores.length, milliseconds: result.milliseconds, rendererBefore: before, rendererAfter: after }));
  } finally { await app.close(); }
});

test("neural voice capture ends a real synthetic Russian command once without waiting for 60 seconds", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-endpoint-turn-"));
  const app = await electron.launch({ args: ["--mute-audio", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--use-file-for-fake-audio-capture=" + resolve("tests/fixtures/endpoint/short.wav"), "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  try {
    const page = await app.firstWindow(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    await page.evaluate(() => {
      const resume = AudioContext.prototype.resume;
      AudioContext.prototype.resume = async function () { await resume.call(this); Object.assign(window, { endpointMicStart: Date.now() }); };
      const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async (constraints) => { const stream = await get(constraints); const setting = stream.getAudioTracks()[0].getSettings(); Object.assign(window, { endpointCaptureSettings: { echoCancellation: setting.echoCancellation, noiseSuppression: setting.noiseSuppression, autoGainControl: setting.autoGainControl, sampleRate: setting.sampleRate } }); return stream; };
    });
    let stt = 0, turns = 0;
    await page.route("**/voice/prepare", (route) => route.fulfill({ json: { ok: true } }));
    await page.route("**/voice/transcribe", async (route) => {
      stt++;
      const timing = await page.evaluate(() => ({ delay: Date.now() - (window as unknown as { endpointMicStart: number }).endpointMicStart, settings: (window as unknown as { endpointCaptureSettings: object }).endpointCaptureSettings }));
      const pcm = await readFile("tests/fixtures/endpoint/short.wav"); const end = (pcm.length - 44) / 32000 - 3;
      console.log("Synthetic Russian capture: " + JSON.stringify({ endpointDelayMsApprox: Math.round(timing.delay - end * 1000), capture: timing.settings }));
      expect(timing.delay - end * 1000).toBeLessThan(1800);
      return route.fulfill({ json: { text: "Поговорим о звёздах" } });
    });
    await page.route("**/voice/synthesize", (route) => route.fulfill({ contentType: "audio/wav", body: Buffer.from(wav(new Float32Array(1600), 16000)) }));
    await page.route("**/chat", (route) => {
      turns++; const assistant = { id: "endpoint-answer", role: "assistant", content: "Хорошо.", created: new Date().toISOString() };
      return route.fulfill({ contentType: "text/event-stream", body: [{ type: "delta", text: "Хорошо." }, { type: "done", message: assistant }].map((event) => "data: " + JSON.stringify(event) + "\n\n").join("") });
    });
    await page.getByRole("button", { name: "Начать разговор", exact: true }).click();
    await expect.poll(() => turns, { timeout: 12000 }).toBe(1);
    await page.getByRole("button", { name: "Завершить разговор", exact: true }).click();
    await expect.poll(() => stt).toBe(1); expect(turns).toBe(1);
    await expect(page.getByRole("button", { name: "Начать разговор", exact: true })).toBeVisible();
    expect(await page.getByRole("alert").count()).toBe(0);
  } finally { await app.close(); }
});

test("endpoint mode, RMS fallback choice and optional Smart Turn persist after restart without downloading a model", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-endpoint-settings-"));
  const launch = () => electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  let app = await launch();
  try {
    let page = await app.firstWindow(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    let downloads = 0;
    const instrument = async () => { await page.route("**/voice/endpoint/install", (route) => { downloads++; return route.abort(); }); };
    await instrument();
    await page.getByRole("button", { name: "⚙ Настройки", exact: true }).click();
    await page.getByRole("tab", { name: "Микрофон и разговор", exact: true }).click();
    const card = page.getByLabel("Завершение голосовой реплики", { exact: true });
    await card.getByLabel("Режим окончания речи").selectOption("dictation");
    await card.getByText("Дополнительно: детектор речи", { exact: true }).click();
    await card.getByLabel("Движок VAD", { exact: true }).selectOption("rms");
    await card.getByRole("switch").check();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Настройки сохранены");
    expect(downloads).toBe(0); await app.close(); app = await launch(); page = await app.firstWindow(); await instrument();
    await page.getByRole("button", { name: "⚙ Настройки", exact: true }).click();
    await page.getByRole("tab", { name: "Микрофон и разговор", exact: true }).click();
    await expect(page.getByLabel("Режим окончания речи")).toHaveValue("dictation");
    await page.getByText("Дополнительно: детектор речи", { exact: true }).click();
    await expect(page.getByLabel("Движок VAD", { exact: true })).toHaveValue("rms");
    await expect(page.getByRole("switch", { name: "Проверять завершённость фразы через Smart Turn", exact: true })).toBeChecked();
    expect(downloads).toBe(0);
  } finally { await app.close(); }
});
