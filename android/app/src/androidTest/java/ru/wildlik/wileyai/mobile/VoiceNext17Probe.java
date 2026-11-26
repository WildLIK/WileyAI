package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Debug;
import android.os.SystemClock;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.*;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipFile;
import org.json.JSONArray;
import org.json.JSONObject;
import org.vosk.Recognizer;

final class VoiceNext17Probe {
    private static final int RATE = 16000, BLOCK = 2048;

    static void run(Context context) throws Exception {
        Path work = context.getCacheDir().toPath().resolve("wiley-next17-probe");
        Path speech = VerifiedModelInstaller.active(context.getFilesDir().toPath().resolve("speech-models"));
        Path giga = GigaAmModelManager.activeModel(context);
        if (speech == null || giga == null) throw new AssertionError("Requires installed models");
        JSONArray checkpoints = new JSONArray();
        memory(checkpoints, "before");
        var runtime = GigaAmRuntime.get(context);
        var engine = new GigaAmSpeechEngine(context, runtime);
        JSONArray results = new JSONArray();
        try (var vosk = SpeechRuntime.acquire(speech)) {
            String grammar = WakeVocabulary.grammar(vosk.model(), WakePhrase.SHORT);
            try (var decoder = new Recognizer(vosk.model(), RATE, grammar)) {
                decoder.setWords(true);
                memory(checkpoints, "vosk_loaded");
                checkVosk(decoder, work.resolve("wake.pcm"));
                System.loadLibrary("wiley_livekit_compare");
                long live = WakeComparison.open(WakeComparison.verifiedModel(context).toString());
                if (live == 0) throw new AssertionError("LiveKit initializer");
                try {
                    short[] fixture = read(work.resolve("live.pcm"));
                    var rule = new WakeComparisonPcm.Decision();
                    int hit = -1;
                    for (int pos = 0; pos < fixture.length; pos += WakeComparisonPcm.BLOCK) {
                        int end = pos + WakeComparisonPcm.BLOCK;
                        if (rule.update(end, WakeComparison.score(live, Arrays.copyOfRange(fixture, pos, end)))) hit = end;
                    }
                    if (hit != 16640) throw new AssertionError("Unexpected frozen LiveKit decision");
                    memory(checkpoints, "vosk_and_livekit");
                    var status = runtime.session.prepare(GigaAmRuntime.model(giga)).result.get(15, TimeUnit.SECONDS);
                    if (status.stopped()) throw new AssertionError("GigaAM preload stopped");
                    memory(checkpoints, "all_three_prepared");
                    results.put(checkGiga(engine, read(work.resolve("time.pcm")), "time", "сколько времени", 1));
                    results.put(checkGiga(engine, read(work.resolve("music.pcm")), "music", "включи музыку", 1));
                    results.put(checkGiga(engine, read(work.resolve("time.pcm")), "quiet_minus_12db", "сколько времени", 4));
                    results.put(checkGiga(engine, new short[0], "silence", "", 1));
                    memory(checkpoints, "all_three_after_decode");
                } finally { WakeComparison.close(live); }
                memory(checkpoints, "livekit_closed");
                runtime.session.release("next17_probe_release", false);
                long until = SystemClock.elapsedRealtime() + 4000;
                while (SystemClock.elapsedRealtime() < until && !"unloaded".equals(runtime.session.latest().result()))
                    SystemClock.sleep(80);
                if (!"unloaded".equals(runtime.session.latest().result())) throw new AssertionError("GigaAM release not observed");
                memory(checkpoints, "gigaam_released");
                memory(checkpoints, "gigaam_released_wait");
            }
        } finally { engine.close(); }
        SpeechRuntime.trim();
        SystemClock.sleep(750);
        memory(checkpoints, "after_vosk_trim");
        JSONObject zip = checkLongExport(work);
        JSONObject report = new JSONObject().put("memory", checkpoints).put("asr_endpoint", results)
                .put("hour_export", zip).put("microphone_opened_by_test", false);
        Files.write(work.resolve("result.json"), report.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    static short[] read(Path file) throws IOException {
        byte[] bytes = Files.readAllBytes(file);
        if (bytes.length <= 0 || bytes.length > RATE * 10 * Short.BYTES || bytes.length % Short.BYTES != 0)
            throw new IOException("Invalid local PCM fixture");
        short[] pcm = new short[bytes.length / 2];
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm);
        return pcm;
    }

    private static void checkVosk(Recognizer decoder, Path fixture) throws Exception {
        short[] pcm = Arrays.copyOf(read(fixture), (int) (Files.size(fixture) / 2 + RATE));
        boolean found = false;
        for (int pos = 0; pos < pcm.length; pos += BLOCK) {
            short[] chunk = Arrays.copyOfRange(pcm, pos, Math.min(pos + BLOCK, pcm.length));
            if (!decoder.acceptWaveForm(chunk, chunk.length)) continue;
            JSONObject finalResult = new JSONObject(decoder.getResult());
            JSONArray words = finalResult.optJSONArray("result");
            double confidence = words == null || words.length() == 0 ? 0 : 1;
            if (words != null) for (int i = 0; i < words.length(); i++)
                confidence = Math.min(confidence, words.getJSONObject(i).optDouble("conf", 0));
            if (WakePhrase.matches(WakePhrase.SHORT, finalResult.optString("text"), confidence)) found = true;
        }
        if (!found) throw new AssertionError("No exact Vosk result on the known archive control");
    }

    static JSONObject checkGiga(GigaAmSpeechEngine engine, short[] pcm, String name, String expected,
            int divisor) throws Exception {
        // Archived speech is followed by a controlled silent tail only for endpoint testing.
        PcmHandoff source = new PcmHandoff(RATE * 2, RATE * 8);
        source.activate(0);
        CountDownLatch done = new CountDownLatch(1);
        String[] output = {null};
        String[] failure = {null};
        long[] ended = {-1};
        long started = SystemClock.elapsedRealtime();
        engine.startFromPcm(4800, new OfflineSpeechEngine.Listener() {
            @Override public void ready(Runnable callback) { callback.run(); }
            @Override public void state(String value) {}
            @Override public void partial(String ignored) {}
            @Override public void result(String text) { output[0] = text; }
            @Override public void error(String error) { failure[0] = "engine_error"; }
            @Override public void finished() { done.countDown(); }
            @Override public void gigaStage(GigaAmSpeechEngine.Stage stage, long at) {
                if (stage == GigaAmSpeechEngine.Stage.ENDPOINT) ended[0] = at - started;
            }
        }, source);
        short[] block = new short[BLOCK];
        long fed = 0;
        while (SystemClock.elapsedRealtime() - started < 5200 && source.isActive()) {
            int take = (int)Math.max(0, Math.min(BLOCK, pcm.length - fed));
            for (int i = 0; i < take; i++) block[i] = (short)(pcm[(int)fed + i] / divisor);
            Arrays.fill(block, take, block.length, (short)0);
            try { source.append(block, block.length); }
            catch (IllegalStateException endedCapture) { if (source.isActive()) throw endedCapture; break; }
            fed += block.length;
            SystemClock.sleep(Math.max(0, started + fed * 1000 / RATE - SystemClock.elapsedRealtime()));
        }
        if (!done.await(15, TimeUnit.SECONDS) || failure[0] != null || output[0] == null)
            throw new AssertionError("GigaAM capture did not finish: " + name);
        String command = WakePhrase.firstCommand(output[0], WakePhrase.SHORT, candidate ->
                PhoneCommands.parse(candidate, true) != null);
        String type = expected.isEmpty() ? "empty" : PhoneCommands.parse(command, true) == null ? "unparsed" : "parsed";
        var stats = source.stats();
        JSONObject row = new JSONObject().put("case", name).put("endpoint_ms", ended[0])
                .put("accepted", stats.acceptedSamples()).put("delivered", stats.deliveredSamples())
                .put("overflow", stats.overflowSamples()).put("discarded", stats.discardedSamples())
                .put("expected_command", expected.equals(command)).put("route", type);
        if (stats.overflowSamples() != 0 || stats.acceptedSamples() != stats.deliveredSamples()
                || expected.isEmpty() && !command.isEmpty())
            throw new AssertionError("Invalid handoff or silence result: " + name);
        return row;
    }

    static void memory(JSONArray rows, String phase) throws Exception {
        SystemClock.sleep(350);
        Debug.MemoryInfo m = new Debug.MemoryInfo();
        Debug.getMemoryInfo(m);
        rows.put(new JSONObject().put("phase", phase).put("pss_kib", m.getTotalPss())
                .put("native_pss_kib", m.nativePss).put("dalvik_pss_kib", m.dalvikPss)
                .put("native_allocated_kib", Debug.getNativeHeapAllocatedSize()/1024)
                .put("java_used_kib", (Runtime.getRuntime().totalMemory()-Runtime.getRuntime().freeMemory())/1024));
    }

    private static JSONObject checkLongExport(Path work) throws Exception {
        long started = SystemClock.elapsedRealtime();
        int samples = 3600 * RATE;
        Path synthetic = Files.createTempDirectory(work, "one-hour-");
        Path raw = synthetic.resolve("test.pcm");
        Path flac = synthetic.resolve("audio.flac");
        Path zip = synthetic.resolve("test.zip");
        try {
            // Safe deterministic PCM for format and storage checks, never part of recognition metrics.
            try (var file = new RandomAccessFile(raw.toFile(), "rw")) {
                file.setLength(samples * 2L);
                file.writeShort(0x3412);
                file.seek(samples * 2L - 2);
                file.writeShort(0x7856);
            }
            AcousticAudio.encodeComparisonFlac(raw, flac);
            if (AcousticAudio.read(flac, 0, 1)[0] != 0x1234 || AcousticAudio.read(flac, samples - 1, 1)[0] != 0x5678)
                throw new AssertionError("Long FLAC sample range");
            Files.write(synthetic.resolve("session.json"), ("{\"kind\":\"format_test\",\"samples\":" + samples + "}")
                    .getBytes(java.nio.charset.StandardCharsets.UTF_8));
            Files.write(synthetic.resolve("timeline.jsonl"), ("{\"type\":\"span\",\"sample\":0,\"end_sample\":" + samples + "}\n")
                    .getBytes(java.nio.charset.StandardCharsets.UTF_8));
            try (var out = Files.newOutputStream(zip)) { WakeComparison.export(synthetic, out); }
            try (var packed = new ZipFile(zip.toFile())) {
                var item = packed.getEntry("audio.flac");
                if (packed.size() != 3 || item == null || item.getSize() != Files.size(flac))
                    throw new AssertionError("Long ZIP entries");
                try (var restored = packed.getInputStream(item); var original = Files.newInputStream(flac)) {
                    byte[] a = new byte[65536], b = new byte[65536];
                    for (int n; (n = readBlock(restored, a)) != 0;)
                        if (readBlock(original, b) != n || !Arrays.equals(a, 0, n, b, 0, n))
                            throw new AssertionError("FLAC bytes differ in ZIP");
                    if (original.read() != -1) throw new AssertionError("Short FLAC entry");
                }
                return new JSONObject().put("span_samples", samples).put("flac_bytes", item.getSize())
                        .put("zip_bytes", Files.size(zip)).put("elapsed_ms", SystemClock.elapsedRealtime()-started);
            }
        } finally { AcousticStore.erase(synthetic); }
    }

    private static int readBlock(InputStream in, byte[] block) throws IOException {
        int offset = 0;
        while (offset < block.length) {
            int count = in.read(block, offset, block.length - offset);
            if (count == -1) break;
            offset += count;
        }
        return offset;
    }
}
