package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Debug;
import android.os.SystemClock;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** Replays archived PCM into the normal GigaAM engine without opening a microphone or running commands. */
final class VoiceNext18Probe {
    static void run(Context context) throws Exception {
        if (!context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE).getBoolean(GigaAmSileroVad.ENABLED, true))
            throw new IllegalStateException("Silero is disabled in the existing app settings");
        Path work = context.getCacheDir().toPath().resolve("wiley-next18-probe");
        Path model = GigaAmModelManager.activeModel(context);
        if (model == null) throw new IllegalStateException("No verified local GigaAM model");
        short[] time = VoiceNext17Probe.read(work.resolve("time.pcm"));
        short[] music = VoiceNext17Probe.read(work.resolve("music.pcm"));
        JSONArray checks = new JSONArray(), memory = new JSONArray(), vad = new JSONArray();
        VoiceNext17Probe.memory(memory, "before");
        for (int i = 0; i < 5; i++) vad.put(measureVad(context, time));
        VoiceNext17Probe.memory(memory, "vad_released");

        GigaAmRuntime runtime = GigaAmRuntime.get(context);
        GigaAmSpeechEngine engine = new GigaAmSpeechEngine(context, runtime);
        try {
            runtime.session.prepare(GigaAmRuntime.model(model)).result.get(15, TimeUnit.SECONDS);
            VoiceNext17Probe.memory(memory, "gigaam_prepared");
            for (int i = 0; i < 3; i++) {
                checks.put(verify(VoiceNext17Probe.checkGiga(engine, time, "quiet_time", "сколько времени", 4)));
                checks.put(verify(VoiceNext17Probe.checkGiga(engine, music, "quiet_music", "включи музыку", 4)));
                VoiceNext17Probe.memory(memory, "after_round_" + i);
            }
            checks.put(verify(VoiceNext17Probe.checkGiga(engine, new short[0], "silence", "", 1)));
        } finally {
            engine.close();
            runtime.session.release("next18_probe_release", false);
        }
        long deadline = SystemClock.elapsedRealtime() + 4000;
        while (SystemClock.elapsedRealtime() < deadline && !"unloaded".equals(runtime.session.latest().result()))
            SystemClock.sleep(80);
        if (!"unloaded".equals(runtime.session.latest().result())) throw new AssertionError("GigaAM release not observed");
        VoiceNext17Probe.memory(memory, "all_released");
        JSONObject report = new JSONObject().put("vad", vad).put("memory", memory)
                .put("capture", checks).put("microphone_opened_by_probe", false);
        Files.write(work.resolve("result.json"), report.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    private static JSONObject verify(JSONObject result) throws Exception {
        if (!result.getBoolean("expected_command")) throw new AssertionError("Unexpected archived replay result");
        return result;
    }

    private static JSONObject measureVad(Context context, short[] clip) throws Exception {
        long start = SystemClock.elapsedRealtime();
        try (GigaAmSileroVad vad = GigaAmSileroVad.open(context.getAssets())) {
            long load = SystemClock.elapsedRealtime() - start;
            long cpu = Debug.threadCpuTimeNanos();
            int hits = 0;
            short[] block = new short[GigaAmSileroVad.HOP];
            for (int pos = 0; pos < clip.length; pos += block.length) {
                Arrays.fill(block, (short) 0);
                int n = Math.min(block.length, clip.length - pos);
                for (int i = 0; i < n; i++) block[i] = (short)(clip[pos+i] / 4);
                if (Boolean.TRUE.equals(vad.observe(block, block.length))) hits++;
            }
            if (hits == 0) throw new AssertionError("Silero missed archived quiet speech");
            return new JSONObject().put("load_ms", load)
                    .put("thread_cpu_ms", (Debug.threadCpuTimeNanos() - cpu)/1e6)
                    .put("audio_ms", clip.length / 16).put("active_hops", hits);
        }
    }
}
