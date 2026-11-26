package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.ContextWrapper;
import android.content.SharedPreferences;
import android.os.Debug;
import android.os.SystemClock;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** Paired real JNI replay and long-run checks with isolated VAD settings and no command execution. */
final class VoiceNext19Probe {
    private static final int RATE = 16000, BLOCK = 2048;
    private static final String PREFS = "wiley-next19-probe";
    private record Fixture(short[] pcm, String label, String hash, String expected) {}

    static void run(Context context) throws Exception {
        Path work = context.getCacheDir().toPath().resolve(PREFS);
        Path model = GigaAmModelManager.activeModel(context);
        if (model == null) throw new IllegalStateException("No verified GigaAM model");
        JSONArray manifest = new JSONArray(new String(Files.readAllBytes(work.resolve("manifest.json")),
                java.nio.charset.StandardCharsets.UTF_8));
        List<Fixture> fixtures = new ArrayList<>();
        for (int i = 0; i < manifest.length(); i++) {
            JSONObject item = manifest.getJSONObject(i);
            String file = item.getString("file");
            if (!file.matches("[0-9]{2}\\.pcm")) throw new IllegalArgumentException("Invalid fixture path");
            Path input = work.resolve(file);
            String hash = item.getString("pcm_sha256");
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(input));
            if (!hash.equals(VerifiedModelInstaller.hex(digest))) throw new IllegalArgumentException("Fixture hash");
            fixtures.add(new Fixture(VoiceNext17Probe.read(input), item.getString("case"), hash, item.getString("expected")));
        }
        if (fixtures.isEmpty()) throw new IllegalArgumentException("Missing fixtures");
        Fixture quiet = fixtures.stream().filter(f -> f.label().equals("next16/time_lk/minus12")).findFirst().orElseThrow();
        JSONArray memory = new JSONArray(), timings = new JSONArray(), paired = new JSONArray(), repeated = new JSONArray();
        VoiceNext17Probe.memory(memory, "before");
        List<Boolean> control = measureVad(context, quiet, 512, timings);
        List<Boolean> partial = measureVad(context, quiet, 173, timings);
        if (!partial.equals(control) || !control.contains(true)) throw new AssertionError("Silero stream or context mismatch");
        GigaAmRuntime runtime = GigaAmRuntime.get(context);
        Context isolated = new ContextWrapper(context) {
            @Override public Context getApplicationContext() { return this; }
            @Override public SharedPreferences getSharedPreferences(String name, int mode) {
                return super.getSharedPreferences(PREFS, MODE_PRIVATE);
            }
        };
        var prefs = isolated.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        GigaAmSpeechEngine engine = new GigaAmSpeechEngine(isolated, runtime);
        try {
            var initial = runtime.session.prepare(GigaAmRuntime.model(model)).result.get(15, TimeUnit.SECONDS);
            if (initial.stopped()) throw new AssertionError("GigaAM cold load stopped");
            VoiceNext17Probe.memory(memory, "gigaam_loaded");
            prefs.edit().putBoolean(GigaAmSileroVad.ENABLED, true).apply();
            for (int i = 1; i <= 50; i++) {
                JSONObject result = replay(engine, quiet, true);
                if (!result.getBoolean("intent_ok")) throw new AssertionError("Repeated quiet fixture routing");
                repeated.put(result);
                if (i == 10 || i == 25 || i == 50) VoiceNext17Probe.memory(memory, "after_" + i);
            }
            release(runtime);
            VoiceNext17Probe.memory(memory, "released");
            SystemClock.sleep(10000);
            VoiceNext17Probe.memory(memory, "idle_10s");
            var reload = runtime.session.prepare(GigaAmRuntime.model(model)).result.get(15, TimeUnit.SECONDS);
            if (reload.stopped() || !reload.metrics().cold()) throw new AssertionError("GigaAM reload");
            VoiceNext17Probe.memory(memory, "reloaded");
            for (boolean enabled : new boolean[]{false, true}) {
                prefs.edit().putBoolean(GigaAmSileroVad.ENABLED, enabled).apply();
                for (Fixture fixture : fixtures) paired.put(replay(engine, fixture, enabled));
            }
            JSONObject report = new JSONObject().put("abi", android.os.Build.SUPPORTED_ABIS[0])
                    .put("vad", timings).put("memory", memory)
                    .put("gigaam_load_ms", initial.metrics().loadMs()).put("gigaam_reload_ms", reload.metrics().loadMs())
                    .put("paired", paired).put("sequential", repeated);
            Files.write(work.resolve("result.json"), report.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } finally {
            engine.close();
            runtime.session.release(PREFS, false);
            context.deleteSharedPreferences(PREFS);
        }
    }

    private static void release(GigaAmRuntime runtime) {
        runtime.session.release(PREFS, false);
        long deadline = SystemClock.elapsedRealtime() + 5000;
        while (SystemClock.elapsedRealtime() < deadline && !"unloaded".equals(runtime.session.latest().result()))
            SystemClock.sleep(80);
        if (!"unloaded".equals(runtime.session.latest().result())) throw new AssertionError("GigaAM release");
    }

    private static List<Boolean> measureVad(Context context, Fixture fixture, int chunk, JSONArray timings) throws Exception {
        long start = SystemClock.elapsedRealtime();
        try (GigaAmSileroVad vad = GigaAmSileroVad.open(context.getAssets())) {
            long load = SystemClock.elapsedRealtime() - start;
            long cpu = Debug.threadCpuTimeNanos();
            List<Boolean> decisions = new ArrayList<>();
            for (int i = 0; i < fixture.pcm().length; i += chunk) {
                short[] input = Arrays.copyOfRange(fixture.pcm(), i, Math.min(i + chunk, fixture.pcm().length));
                Boolean decision = vad.observe(input, input.length);
                if (decision != null) decisions.add(decision);
            }
            double elapsed = (Debug.threadCpuTimeNanos() - cpu) / 1e6;
            timings.put(new JSONObject().put("chunk", chunk).put("load_ms", load)
                    .put("cpu_ms_per_second", elapsed * RATE / fixture.pcm().length)
                    .put("decisions", decisions.size()).put("unprocessed_partial_samples", vad.pending()));
            return decisions;
        }
    }

    private static JSONObject replay(GigaAmSpeechEngine engine, Fixture fixture, boolean silero) throws Exception {
        PcmHandoff source = new PcmHandoff(RATE * 2, RATE * 8);
        source.activate(0);
        long started = SystemClock.elapsedRealtime();
        CountDownLatch finished = new CountDownLatch(1);
        String[] output = {null};
        boolean[] error = {false};
        long[] onset = {-1}, endpoint = {-1}, decode = {-1}, completed = {-1};
        engine.startFromPcm(5900, new OfflineSpeechEngine.Listener() {
            public void ready(Runnable callback) { throw new AssertionError("External PCM requested microphone"); }
            public void state(String text) { if (text.startsWith("Слышу речь")) onset[0] = SystemClock.elapsedRealtime()-started; }
            public void partial(String text) {}
            public void error(String text) { error[0] = true; }
            public void result(String text) { output[0] = text; }
            public void finished() { completed[0] = SystemClock.elapsedRealtime()-started; finished.countDown(); }
            public void gigaStage(GigaAmSpeechEngine.Stage stage, long value) {
                if (stage == GigaAmSpeechEngine.Stage.ENDPOINT) endpoint[0] = value-started;
                if (stage == GigaAmSpeechEngine.Stage.DECODE_DURATION) decode[0] = value;
            }
        }, source);
        short[] pcm = fixture.pcm();
        int fed = 0;
        while (source.isActive() && fed < pcm.length) {
            short[] block = Arrays.copyOfRange(pcm, fed, Math.min(fed + BLOCK, pcm.length));
            try { source.append(block, block.length); }
            catch (IllegalStateException closed) { if (source.isActive()) throw closed; break; }
            fed += block.length;
            SystemClock.sleep(Math.max(0, started + fed * 1000L / RATE - SystemClock.elapsedRealtime()));
        }
        if (!finished.await(17, TimeUnit.SECONDS) || error[0] || output[0] == null)
            throw new AssertionError("Replay failed: " + fixture.label());
        PcmHandoff.Stats count = source.stats();
        if (count.overflowSamples() != 0 || count.discardedSamples() != 0
                || count.acceptedSamples() != count.deliveredSamples()) throw new AssertionError("PCM loss");
        String text = output[0];
        String extracted = WakePhrase.firstCommand(text, WakePhrase.SHORT, candidate -> {
            var parsed = PhoneCommands.parse(candidate, true);
            return parsed != null && !parsed.kind.equals("open") && !parsed.kind.equals("media_search")
                    && !parsed.kind.equals("media_play_search") && !StructuredActionAdapter.requiresPlan(candidate);
        });
        var route = PhoneCommands.parse(extracted, true);
        String intent = route == null ? "" : route.kind + ":" + route.value;
        boolean time = fixture.expected().equals("info:time"), music = fixture.expected().equals("media:play");
        boolean first = time && extracted.startsWith("сколько ") || music && extracted.startsWith("включи ");
        boolean words = time && text.matches("(?s).*сколько .*врем(?:я|ени).*")
                || music && text.matches("(?s).*включи .*музыку.*");
        return new JSONObject().put("case", fixture.label()).put("mode", silero ? "silero" : "legacy")
                .put("input_hash", fixture.hash()).put("expected", fixture.expected()).put("heard", !text.isBlank())
                .put("first_word", first).put("expected_words", words).put("intent", intent)
                .put("intent_ok", intent.equals(fixture.expected())).put("onset_ms", onset[0])
                .put("endpoint_ms", endpoint[0]).put("decode_ms", decode[0]).put("total_ms", completed[0])
                .put("accepted_samples", count.acceptedSamples()).put("delivered_samples", count.deliveredSamples());
    }
}
