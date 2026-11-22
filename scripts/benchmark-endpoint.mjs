// Run after benchmark-endpoint.py generated the common corpus and native scores.
// No microphone, player controls, LLM calls, or external network requests.
import { readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { join } from "node:path";
import { platform, release, arch, cpus } from "node:os";
import { SpeechSegmenter } from "../src/voice/speech.ts";
import { EndpointDetector } from "../src/voice/endpoint.ts";

const root = "local/review/voice33";
const native = await Promise.all(["ten", "silero", "webrtc"].map(async (engine) => JSON.parse(await readFile(join(root, engine + "-results.json"), "utf8"))));
const cases = native[1].cases;
const python = process.env.WILEYAI_PYTHON || ".venv/Scripts/python.exe";
const child = spawn(python, ["-m", "core.smart_turn_worker", join(root, "smart-turn-v3.2-cpu.onnx")], { windowsHide: true, env: { ...process.env, OMP_NUM_THREADS: "1", OPENBLAS_NUM_THREADS: "1", MKL_NUM_THREADS: "1" }, stdio: ["pipe", "pipe", "inherit"] });
const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
const started = performance.now();
const ready = JSON.parse((await lines.next()).value);
if (!ready.ready) throw new Error("Smart Turn did not initialize");
const startupMs = performance.now() - started;
const semantic = [];
const outputs = [];
try {
  for (const mode of ["rms", "silero", "silero+smart-turn"]) {
    const results = [];
    for (const item of cases) {
      const bytes = await readFile(item.path);
      const audio = new Float32Array((bytes.length - 44) / 2);
      for (let i = 0; i < audio.length; i++) audio[i] = bytes.readInt16LE(44 + i * 2) / 32768;
      const sent = []; let clock = 0, pending;
      const check = async (samples) => {
        const pcm = Buffer.alloc(samples.length * 2);
        for (let i = 0; i < samples.length; i++) pcm.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32767))), i * 2);
        const began = performance.now();
        child.stdin.write(JSON.stringify({ pcm: pcm.toString("base64") }) + "\n");
        const result = JSON.parse((await lines.next()).value);
        const milliseconds = performance.now() - began;
        semantic.push({ case: item.name, score: result.score, milliseconds });
        return result.score > .5;
      };
      const detector = mode === "rms" ? new SpeechSegmenter(16000, { maximumSpeechMs: 60000 })
        : new EndpointDetector(16000, { mode: "auto", maximumSpeechMs: 60000 }, mode.includes("smart") ? (samples) => { pending = check(samples); return pending; } : undefined, () => sent.push(clock));
      const hop = mode === "rms" ? 320 : item.hop;
      for (let at = 0, frame = 0; at < audio.length; at += hop, frame++) {
        clock = Math.min(audio.length, at + hop) / 16000;
        const pcm = audio.slice(at, at + hop);
        const segment = mode === "rms" ? detector.push(pcm) : detector.push(pcm, item.probabilities[frame]);
        if (segment) sent.push(clock);
        // Offline deterministic replay waits for the measured local semantic
        // decision at a pause. Resumption/cancellation races have separate tests.
        if (detector.checking) {
          await new Promise((resolve) => setImmediate(resolve));
          await pending; await new Promise((resolve) => setImmediate(resolve));
        }
      }
      const end = item.speech.at(-1)?.[1];
      const semanticMs = mode.includes("smart") ? semantic.filter((row) => row.case === item.name).at(-1)?.milliseconds || 0 : 0;
      results.push({ name: item.name, end_delay_ms: end && sent.length ? Math.round((sent.at(-1) - end) * 1000 + semanticMs) : null,
        early_cut: !!(end && sent.some((time) => time < end - .2)), missed: !!(end && !sent.length), false_turns: end ? 0 : sent.length, sent });
    }
    outputs.push({ mode, cases: results });
  }
  const resourceSummary = native.map(({ engine, initialization_ms, cpu_ms, peak_rss_mb, added_rss_mb, frame_p95_ms, audio_seconds }) => ({ engine, initialization_ms, cpu_ms, peak_rss_mb, added_rss_mb, frame_p95_ms, audio_seconds }));
  const smartResource = JSON.parse(await readFile(join(root, "smart-resource.json"), "utf8").catch(() => "null"));
  const candidateQuality = native.map(({ engine, cases }) => ({ engine, policy: "common 700 ms pause, 128 ms minimum speech, score >= 0.5", cases: cases.map(({ name, endpoint_delay_ms, cut, missed, false_turns }) => ({ name, endpoint_delay_ms, cut, missed, false_turns })) }));
  const report = { date: new Date().toISOString(), environment: { platform: platform(), release: release(), arch: arch(), cpu: cpus()[0]?.model, logical_cpus: cpus().length, node: process.version }, corpus: "9 synthetic Russian TTS/noise cases, 67.453625 seconds; no owner microphone recordings", labels: "inserted synthetic speech spans; not human phoneme or semantic labels", semantic_replay: "measured local inference at VAD pauses, no real-time audio capture", resources: resourceSummary, candidate_quality: candidateQuality, smart_turn: { model: "v3.2 CPU int8", startup_ms: startupMs, calls: semantic, resources: smartResource }, pipelines: outputs };
  await writeFile(join(root, "endpoint-comparison.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally { child.stdin.end(); child.kill(); }
