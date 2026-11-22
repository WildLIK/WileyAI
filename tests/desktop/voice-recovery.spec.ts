import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, readdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { wav } from "../../src/voice/speech";

// Every microphone is Chromium's file-backed virtual device. STT, chat and TTS
// are intercepted before the backend: no model can execute a host command.
for (const mode of ["normal", "music-smart", "music-smart-missing", "worker-error", "worker-deadline", "music-no-name", "empty-stt"] as const) {
  test("voice recovery on app:// with virtual microphone: " + mode, async () => {
    const data = await mkdtemp(join(tmpdir(), "wiley-voice-recovery-"));
    const app = await electron.launch({ args: ["--mute-audio", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--use-file-for-fake-audio-capture=" + resolve("tests/fixtures/endpoint/short.wav"), "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
    try {
      const page = await app.firstWindow(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
      const music = mode !== "normal";
      await page.evaluate(async ({ music, smart }) => {
        const c = await window.wiley.connection();
        const headers = { Authorization: "Bearer " + c.token, "Content-Type": "application/json" };
        const settings = await (await fetch(c.url + "/settings", { headers })).json();
        const result = await fetch(c.url + "/settings", { method: "PUT", headers, body: JSON.stringify({ ...settings, stt_environment: music ? "music" : "normal", conversation_vad: "auto", conversation_endpoint_mode: "auto", conversation_smart_turn: smart, conversation_wake_word: "Уайли", conversation_wake_required: false, conversation_barge_in: false, voice_diagnostics: true }) });
        if (!result.ok) throw new Error("Test profile update failed");
      }, { music, smart: mode.startsWith("music-smart") });
      await page.reload(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
      await page.evaluate((mode) => {
        const stats = { pcm: 0, warm: [] as object[], scores: [] as number[], tracks: [] as MediaStreamTrack[], injected: false, started: 0 };
        Object.assign(window, { recoveryStats: stats });
        const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = async (constraints) => { const stream = await original(constraints); stats.tracks.push(...stream.getTracks()); return stream; };
        const resume = AudioContext.prototype.resume;
        AudioContext.prototype.resume = async function () { await resume.call(this); stats.started = performance.now(); };
        const Worklet = window.AudioWorkletNode;
        window.AudioWorkletNode = class extends Worklet {
          constructor(context: BaseAudioContext, name: string, options?: AudioWorkletNodeOptions) {
            super(context, name, options);
            let handler: ((event: MessageEvent) => void) | null = null;
            const buffered: MessageEvent[] = [];
            Object.defineProperty(this.port, "onmessage", { configurable: true, get: () => handler, set: (value) => { handler = value; } });
            this.port.addEventListener("message", (event) => {
              stats.pcm++;
              // Deliver the first 700 ms as one burst. Audio duration must not
              // be confused with the amount of wall-clock inference time.
              if (stats.pcm <= 35) { buffered.push(event); if (stats.pcm < 35) return; for (const value of buffered) handler?.(value); return; }
              handler?.(event);
              if (stats.pcm === 80 && mode === "normal") { const until = performance.now() + 220; while (performance.now() < until) { /* bounded UI stall */ } }
            });
            this.port.start();
          }
        };
        const NativeWorker = window.Worker;
        window.Worker = class extends NativeWorker {
          constructor(url: string | URL, options?: WorkerOptions) {
            super(url, options);
            if (!String(url).includes("vad-worker")) return;
            let handler: ((event: MessageEvent) => void) | null = null, voiced = 0;
            Object.defineProperty(this, "onmessage", { configurable: true, get: () => handler, set: (value) => { handler = value; } });
            this.addEventListener("message", (event) => {
              if (event.data.ready) stats.warm.push({ initializationMs: event.data.initializationMs, warmupMs: event.data.warmupMs });
              if (Number.isFinite(event.data.milliseconds)) stats.scores.push(event.data.milliseconds);
              if (event.data.score > .8) voiced++;
              if (!stats.injected && voiced >= 12 && mode === "worker-error") {
                stats.injected = true; handler?.({ data: { error: "test_inference_failure", epoch: event.data.epoch, id: event.data.id } } as MessageEvent); return;
              }
              if (voiced >= 12 && mode === "worker-deadline") { stats.injected = true; setTimeout(() => handler?.(event), 700); return; }
              handler?.(event);
            });
          }
        };
      }, mode);
      let stt = 0, turns = 0, tts = 0; const records: object[] = [];
      await page.route("**/voice/prepare", (route) => route.fulfill({ json: { ok: true } }));
      await page.route("**/voice/endpoint/check", (route) => route.fulfill({ json: mode === "music-smart-missing" ? { available: false, reason: "not_installed" } : { available: true, complete: true, milliseconds: 3 } }));
      await page.route("**/voice/endpoint/release", (route) => route.fulfill({ json: { ok: true } }));
      await page.route("**/voice/transcribe", async (route) => {
        stt++;
        const upload = route.request().postDataBuffer()!, offset = upload.indexOf(Buffer.from("RIFF"));
        expect(offset).toBeGreaterThan(0); expect(upload.readUInt32LE(offset + 24)).toBe(16000); expect(upload.readUInt16LE(offset + 22)).toBe(1);
        const duration = upload.readUInt32LE(offset + 40) / 32;
        expect(duration).toBeGreaterThan(700); expect(duration).toBeLessThan(4000);
        const elapsed = await page.evaluate(() => performance.now() - (window as any).recoveryStats.started);
        records.push({ durationMs: duration, captureToSttMs: Math.round(elapsed) });
        return route.fulfill({ json: { text: mode === "empty-stt" ? "" : mode === "music-no-name" || !music ? "Привет" : "Уайли, привет" } });
      });
      await page.route("**/chat", (route) => {
        turns++; const request = route.request().postDataJSON(); expect(request.text.toLowerCase()).toBe("привет");
        const user = { id: "recovery-u" + turns, role: "user", content: request.text, created: new Date().toISOString() };
        const message = { id: "recovery-a" + turns, role: "assistant", content: "Я тебя слышу.", created: new Date().toISOString() };
        return route.fulfill({ contentType: "text/event-stream", body: [{ type: "user", message: user }, { type: "delta", text: message.content }, { type: "done", message }].map((event) => "data: " + JSON.stringify(event) + "\n\n").join("") });
      });
      await page.route("**/voice/synthesize", (route) => { tts++; return route.fulfill({ contentType: "audio/wav", body: Buffer.from(wav(new Float32Array(3200), 16000)) }); });
      await page.getByRole("button", { name: "Начать разговор", exact: true }).click();
      const diagnostics = page.getByLabel("Диагностика голосового диалога", { exact: true });
      await expect.poll(() => stt, { timeout: 14000 }).toBe(1);
      await diagnostics.locator("summary").click();
      const rejected = mode === "music-no-name" || mode === "empty-stt";
      if (rejected) {
        await expect(diagnostics.locator(`[data-voice-event="${mode === "empty-stt" ? "stt_empty" : "activation_rejected"}"]`)).toBeVisible();
        expect(turns).toBe(0); expect(tts).toBe(0);
      } else {
        await expect.poll(() => tts, { timeout: 5000 }).toBe(1);
        await expect(diagnostics.locator('[data-voice-event="request_dispatched"]')).toBeVisible();
        await expect(diagnostics.locator('[data-voice-event="response_started"]')).toBeVisible();
        expect(turns).toBe(1);
      }
      await expect(page.locator(".conversation-phase")).toHaveText(music ? "Жду обращения" : "Ожидаю следующую реплику");
      if (mode.startsWith("worker-")) await expect(diagnostics.locator('[data-voice-event="vad_fallback_rms"]')).toHaveCount(1);
      else await expect(diagnostics.locator('[data-voice-event="vad_fallback_rms"]')).toHaveCount(0);
      if (mode === "worker-deadline") await expect(diagnostics.locator('[data-voice-event="vad_timeout"]')).toHaveCount(1);
      if (mode === "normal") {
        await expect.poll(() => turns, { timeout: 10000 }).toBe(2);
        await expect.poll(() => tts).toBe(2); expect(stt).toBe(2);
      }
      await page.getByRole("button", { name: "Завершить разговор", exact: true }).click();
      await expect.poll(() => page.evaluate(() => (window as any).recoveryStats.tracks.map((track: MediaStreamTrack) => track.readyState))).toEqual(["ended"]);
      const stats = await page.evaluate(() => { const s = (window as any).recoveryStats; const sorted = [...s.scores].sort((a: number, b: number) => a - b); return { frames: s.pcm, initialization: s.warm, vadFrames: sorted.length, vadP95Ms: sorted[Math.floor(sorted.length * .95)], vadMaxMs: sorted.at(-1), injected: s.injected }; });
      console.log("Voice recovery integration: " + JSON.stringify({ mode, stt, turns, tts, records, ...stats }));
    } finally { await app.close(); }
  });
}

test("cold and repeated bundled Silero initialization and frame timings offline", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-voice-profile-"));
  const app = await electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  try {
    const page = await app.firstWindow(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    const worker = (await readdir("dist/assets")).find((name) => /^vad-worker-.*\.js$/.test(name))!;
    const input = await readFile("tests/fixtures/endpoint/short.wav");
    const samples = [...new Int16Array(input.buffer.slice(input.byteOffset + 44, input.byteOffset + input.length))].map((n) => n / 32768);
    await page.context().setOffline(true);
    const before = await app.evaluate(({ app }) => app.getAppMetrics().filter((m) => m.type === "Tab").map((m) => ({ cpuSeconds: m.cpu.cumulativeCPUUsage, ramKiB: m.memory.workingSetSize })));
    const profiles = [];
    for (let run = 0; run < 2; run++) profiles.push(await page.evaluate(async ({ worker, samples }) => await new Promise<object>((resolve, reject) => {
      const began = performance.now(), engine = new Worker("app://wileyai/assets/" + worker, { type: "module" });
      let ready: any, count = 0; const times: number[] = [], scores: number[] = [];
      const timer = setTimeout(() => { engine.terminate(); reject(new Error("Silero profiling deadline")); }, 15000);
      engine.onerror = () => { clearTimeout(timer); engine.terminate(); reject(new Error("Silero worker failure")); };
      engine.onmessage = ({ data }) => {
        if (data.error) { clearTimeout(timer); engine.terminate(); reject(new Error(data.error)); return; }
        if (data.ready) { ready = data; for (let at = 0; at < samples.length; at += 512) { const audio = new Float32Array(512); audio.set(samples.slice(at, at + 512)); engine.postMessage({ id: ++count, epoch: 0, audio }); } }
        else {
          times.push(data.milliseconds); scores.push(data.score);
          if (times.length === count) { clearTimeout(timer); engine.terminate(); const sorted = [...times].sort((a, b) => a - b); resolve({ initializationMs: ready.initializationMs, warmupMs: ready.warmupMs, frames: count, firstFrameMs: times[0], p95Ms: sorted[Math.floor(sorted.length * .95)], maxMs: sorted.at(-1), totalMs: performance.now() - began, hasSpeech: scores.some((score) => score > .8) }); }
        }
      };
    }), { worker, samples }));
    expect(profiles.every((p: any) => p.hasSpeech)).toBe(true);
    const after = await app.evaluate(({ app }) => app.getAppMetrics().filter((m) => m.type === "Tab").map((m) => ({ cpuSeconds: m.cpu.cumulativeCPUUsage, ramKiB: m.memory.workingSetSize, peakKiB: m.memory.peakWorkingSetSize })));
    console.log("Voice recovery profiling: " + JSON.stringify({ profiles, rendererBefore: before, rendererAfter: after }));
  } finally { await app.close(); }
});
