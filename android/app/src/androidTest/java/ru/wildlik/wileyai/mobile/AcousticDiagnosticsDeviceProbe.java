package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaPlayer;
import android.os.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;
import java.util.zip.ZipInputStream;
import org.json.*;

final class AcousticDiagnosticsDeviceProbe {
    static String run(Context target) throws Exception {
        Path dir = Files.createTempDirectory(target.getCacheDir().toPath(), "acoustic-test-");
        AcousticDiagnostics diagnostics = new AcousticDiagnostics(target, dir);
        long begin = SystemClock.elapsedRealtime();
        long cpuStart = android.os.Process.getElapsedCpuTime();
        try {
            diagnostics.begin("guided", 10, true, 0, 0);
            awaitReady(diagnostics);
            short[] block = new short[2048];
            for (int i = 0; i < block.length; i++) block[i] = (short)(i * 31);
            for (int i = 0; i < 64; i++) diagnostics.feed(null, 15, i * 2048L, block, block.length);
            JSONObject finalJson = AcousticStore.fields("text", "вай ли");
            if (!diagnostics.candidate(15, new WakeActivation(123456, 0, 3, false, 1000, 10), "[\"вай ли\",\"[unk]\"]",
                    "вайли", finalJson, "exact_wake", 1, 64 * 2048L, 2000)) throw new AssertionError("wake not suppressed");
            for (int i = 64; i < 89; i++) diagnostics.feed(null, 15, i * 2048L, block, block.length);
            diagnostics.marker(true, 1, 2);
            diagnostics.stop("instrumentation");
            List<JSONObject> events = AcousticDiagnosticsDeviceProbe.<List<JSONObject>>request(diagnostics::list);
            require(events.size() == 2);
            JSONObject event = events.stream().filter(x -> x.optString("id").equals("123456")).findFirst().orElseThrow();
            Path clip = AcousticDiagnosticsDeviceProbe.<Path>request(done -> diagnostics.openAudio(event, done));
            require(event.optInt("samples") == 176000 && event.optInt("post_samples") == 48000 && clip != null);
            short[] decoded = AcousticAudio.read(clip, 0, 176000);
            require(decoded[0] == block[(64 * 2048 - 128000) % 2048] && decoded[127999] == block[2047] && decoded[128000] == block[0]);
            MediaExtractor extractor = new MediaExtractor();
            try {
                extractor.setDataSource(clip.toString());
                MediaFormat format = extractor.getTrackFormat(0);
                require("audio/flac".equals(format.getString(MediaFormat.KEY_MIME))
                        && format.getInteger(MediaFormat.KEY_SAMPLE_RATE) == 16000);
            } finally { extractor.release(); }
            JSONObject previewEvent = new JSONObject(event.toString()).put("samples", 3200);
            Path preview = AcousticDiagnosticsDeviceProbe.<Path>request(done -> diagnostics.preparePlayback(previewEvent, done));
            require(preview != null && Arrays.equals(Arrays.copyOf(decoded, 3200), AcousticAudio.read(preview, 0, 3200)));
            MediaPlayer playback = new MediaPlayer();
            try {
                CountDownLatch finished = new CountDownLatch(1);
                AtomicReference<Boolean> complete = new AtomicReference<>(false);
                playback.setDataSource(preview.toString());
                playback.setVolume(0, 0);
                playback.setOnCompletionListener(player -> { complete.set(true); finished.countDown(); });
                playback.setOnErrorListener((player, what, extra) -> { finished.countDown(); return true; });
                playback.prepare();
                require(playback.getDuration() == 200);
                playback.start();
                require(finished.await(8, TimeUnit.SECONDS) && complete.get());
            } finally {
                playback.release();
                diagnostics.closePlayback(preview);
            }
            AcousticDiagnosticsDeviceProbe.<String>request(done -> diagnostics.relabel(event, 5, "искусственные данные", done));
            List<JSONObject> relabeled = AcousticDiagnosticsDeviceProbe.<List<JSONObject>>request(diagnostics::list);
            require(relabeled.stream().anyMatch(x -> x.optString("id").equals("123456") && x.optInt("label") == 5));
            ByteArrayOutputStream zip = new ByteArrayOutputStream();
            String exported = request(done -> diagnostics.export(() -> zip, done));
            require(exported.equals("ZIP сохранён"));
            Set<String> names = new HashSet<>();
            try (ZipInputStream input = new ZipInputStream(new ByteArrayInputStream(zip.toByteArray()))) {
                for (var item = input.getNextEntry(); item != null; item = input.getNextEntry()) names.add(item.getName());
            }
            require(names.size() == 11 && names.contains(AcousticStore.ROOT + "recognition.jsonl"));
            AcousticDiagnosticsDeviceProbe.<String>request(done -> diagnostics.remove(event, done));
            require(!Files.exists(clip) && !Files.exists(preview));

            diagnostics.begin("continuous", 5, false, 0, 0);
            awaitReady(diagnostics);
            diagnostics.feed(null, 29, 0, block, block.length);
            diagnostics.marker(true, 0, 0);
            diagnostics.captureEnd(29, 1);
            diagnostics.feed(null, 30, 0, block, block.length);
            diagnostics.stop("instrumentation");
            List<JSONObject> continuous = AcousticDiagnosticsDeviceProbe.<List<JSONObject>>request(diagnostics::list);
            JSONObject parent = continuous.stream().filter(x -> x.optString("kind").equals("continuous")).findFirst().orElseThrow();
            require(parent.optInt("samples") == block.length * 2 && parent.getJSONArray("spans").length() == 2);
            require(continuous.stream().filter(x -> x.has("audio_ref")).count() == 1);
            request(diagnostics::clear);
            require(!Files.exists(dir) && !diagnostics.active());
            Debug.MemoryInfo memory = new Debug.MemoryInfo();
            Debug.getMemoryInfo(memory);
            return "flac_android_extractor=passed; pcm_match=passed; wav_playback=completed; zip_entries=" + names.size()
                    + "; elapsed_ms=" + (SystemClock.elapsedRealtime() - begin)
                    + "; cpu_ms=" + (android.os.Process.getElapsedCpuTime() - cpuStart) + "; process_pss_kib=" + memory.getTotalPss();
        } finally {
            diagnostics.stop("instrumentation_cleanup");
            request(diagnostics::clear);
        }
    }
    private static void require(boolean value) { if (!value) throw new AssertionError("acoustic probe assertion"); }
    private static void awaitReady(AcousticDiagnostics diagnostics) {
        for (int i = 0; i < 120 && !diagnostics.ready(); i++) SystemClock.sleep(25);
        require(diagnostics.ready());
    }
    private static <T> T request(Consumer<Consumer<T>> action) throws Exception {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<T> out = new AtomicReference<>();
        action.accept(value -> { out.set(value); latch.countDown(); });
        require(latch.await(20, TimeUnit.SECONDS));
        return out.get();
    }
}
