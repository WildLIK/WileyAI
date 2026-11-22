import * as ort from "onnxruntime-web/wasm";
import wasmUrl from "../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm?url";
import runtimeUrl from "../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.mjs?url";
import modelUrl from "../../assets/voice/silero_vad_v5.onnx?url";

ort.env.wasm.numThreads = 1;
ort.env.wasm.proxy = false;
ort.env.wasm.wasmPaths = { wasm: wasmUrl, mjs: runtimeUrl };
let state = new Float32Array(256), context = new Float32Array(64);
const session = (async () => {
  const began = performance.now();
  const model = await ort.InferenceSession.create(modelUrl, { executionProviders: ["wasm"], graphOptimizationLevel: "all" });
  const prepared = performance.now();
  // A loaded graph is not yet a warmed inference engine. Warm on silence before
  // capture starts, rather than charging cold kernel setup to a 500 ms PCM deadline.
  await model.run({ input: new ort.Tensor("float32", new Float32Array(576), [1, 576]), state: new ort.Tensor("float32", new Float32Array(256), [2, 1, 128]), sr: new ort.Tensor("int64", BigInt64Array.of(16000n), []) });
  self.postMessage({ ready: true, initializationMs: prepared - began, warmupMs: performance.now() - prepared });
  return model;
})();
let pending = Promise.resolve();
self.onmessage = ({ data }) => {
  pending = pending.then(async () => {
    if (data.reset) { state.fill(0); context.fill(0); return; }
    const model = await session, audio: Float32Array = data.audio;
    const began = performance.now();
    const input = new Float32Array(576); input.set(context); input.set(audio, 64);
    const output = await model.run({ input: new ort.Tensor("float32", input, [1, 576]), state: new ort.Tensor("float32", state, [2, 1, 128]), sr: new ort.Tensor("int64", BigInt64Array.of(16000n), []) });
    state = new Float32Array(output.stateN.data as Float32Array);
    context = input.slice(-64);
    self.postMessage({ id: data.id, epoch: data.epoch, score: Number(output.output.data[0]), milliseconds: performance.now() - began });
  }).catch(() => { self.postMessage({ error: "inference_failed", epoch: data.epoch, id: data.id }); });
};
void session.catch(() => self.postMessage({ error: "initialization_failed" }));
