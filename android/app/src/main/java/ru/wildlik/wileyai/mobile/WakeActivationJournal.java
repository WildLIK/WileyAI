package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Local-only activation diagnostic journal for everyday Stage 1 testing.
 * Stores pre/post 16 kHz WAV clips, confidence, CAM++ speaker similarity, mic route, TTS state,
 * latencies, accept/reject reason, and user feedback (manual false alarms & missed commands).
 */
final class WakeActivationJournal {
    static final String PREFS = "wiley-mobile";
    static final String KEY_ENABLED = "wake_activation_journal_enabled";
    static final int SAMPLE_RATE = 16000;
    static final int PRE_SAMPLES = 24000;  // 1.5 s
    static final int POST_SAMPLES = 24000; // 1.5 s
    private static final int MAX_EVENTS = 120;
    private static final ExecutorService IO = Executors.newSingleThreadExecutor();

    record Entry(
            String id,
            long timestampMs,
            String timestampUtc,
            String engine,
            double confidence,
            double speakerSimilarity,
            double speakerThreshold,
            double livekitThreshold,
            String micSource,
            boolean ttsSpeaking,
            long wakeLatencyMs,
            long camLatencyMs,
            String outcome,
            String reason,
            String userLabel,
            String asrText,
            boolean hasPreWav,
            boolean hasPostWav) {
        String summary() {
            String sim = Double.isNaN(speakerSimilarity) ? "—" : String.format(Locale.ROOT, "%.3f", speakerSimilarity);
            String conf = Double.isNaN(confidence) ? "—" : String.format(Locale.ROOT, "%.3f", confidence);
            String mark = userLabel.isEmpty() ? "" : " [" + userLabel + "]";
            return String.format(Locale.ROOT, "%s · %s · conf=%s · sim=%s · %s%s",
                    outcome, engine, conf, sim, micSource, mark);
        }
    }

    static boolean isEnabled(Context context) {
        return prefs(context).getBoolean(KEY_ENABLED, true);
    }

    static void setEnabled(Context context, boolean enabled) {
        prefs(context).edit().putBoolean(KEY_ENABLED, enabled).apply();
    }

    static Path rootDir(Context context) {
        return context.getApplicationContext().getNoBackupFilesDir().toPath().resolve("wake-activation-journal");
    }

    static String recordEventAsync(
            Context context,
            String engine,
            double confidence,
            double speakerSimilarity,
            double speakerThreshold,
            double livekitThreshold,
            String micSource,
            boolean ttsSpeaking,
            long wakeLatencyMs,
            long camLatencyMs,
            String outcome,
            String reason,
            short[] prePcm) {
        if (!isEnabled(context)) return null;
        String id = System.currentTimeMillis() + "_" + UUID.randomUUID().toString().substring(0, 8);
        short[] copy = prePcm == null ? null : Arrays.copyOf(prePcm, Math.min(prePcm.length, PRE_SAMPLES));
        Context app = context.getApplicationContext();
        long now = System.currentTimeMillis();
        IO.execute(() -> {
            try {
                Path dir = rootDir(app).resolve(id);
                Files.createDirectories(dir);
                if (copy != null && copy.length > 0) {
                    writeWav(dir.resolve("pre.wav"), copy, copy.length);
                }
                JSONObject meta = new JSONObject();
                meta.put("id", id);
                meta.put("timestamp_ms", now);
                meta.put("timestamp_utc", Instant.ofEpochMilli(now).toString());
                meta.put("engine", engine);
                meta.put("confidence", Double.isFinite(confidence) ? confidence : JSONObject.NULL);
                meta.put("speaker_similarity", Double.isFinite(speakerSimilarity) ? speakerSimilarity : JSONObject.NULL);
                meta.put("speaker_threshold", Double.isFinite(speakerThreshold) ? speakerThreshold : JSONObject.NULL);
                meta.put("livekit_threshold", Double.isFinite(livekitThreshold) ? livekitThreshold : JSONObject.NULL);
                meta.put("mic_source", micSource == null ? "unknown" : micSource);
                meta.put("tts_speaking", ttsSpeaking);
                meta.put("wake_latency_ms", wakeLatencyMs);
                meta.put("cam_latency_ms", camLatencyMs);
                meta.put("outcome", outcome);
                meta.put("reason", reason);
                meta.put("user_label", "");
                meta.put("asr_text", "");
                Files.write(dir.resolve("meta.json"), meta.toString(2).getBytes(StandardCharsets.UTF_8));
                pruneOldest(rootDir(app));
            } catch (Exception ignored) {}
        });
        return id;
    }

    static void savePostAudioAsync(Context context, String eventId, short[] postPcm, int length) {
        if (eventId == null || postPcm == null || length <= 0 || !isEnabled(context)) return;
        short[] copy = Arrays.copyOf(postPcm, Math.min(length, POST_SAMPLES));
        Context app = context.getApplicationContext();
        IO.execute(() -> {
            try {
                Path dir = rootDir(app).resolve(eventId);
                if (Files.isDirectory(dir)) {
                    writeWav(dir.resolve("post.wav"), copy, copy.length);
                }
            } catch (Exception ignored) {}
        });
    }

    static void recordMissedCommandAsync(Context context, short[] pcm, int length, String note) {
        Context app = context.getApplicationContext();
        short[] copy = pcm == null ? null : Arrays.copyOf(pcm, length);
        String engine = switch (WakeSettings.wakeEngine(app)) {
            case WakeSettings.ENGINE_LIVEKIT_V2 -> "livekit_c_v2";
            case WakeSettings.ENGINE_LIVEKIT_V2_CAM -> "livekit_c_v2_cam";
            default -> "vosk";
        };
        double lkThr = WakeSettings.liveKitThreshold(app);
        double camThr = OwnerSpeakerFilter.threshold(app);
        boolean tts = HandsFreeService.acousticSpeaking();
        String route = AudioRouteManager.routeSummary(app);
        String id = System.currentTimeMillis() + "_missed_" + UUID.randomUUID().toString().substring(0, 6);
        long now = System.currentTimeMillis();
        IO.execute(() -> {
            try {
                Path dir = rootDir(app).resolve(id);
                Files.createDirectories(dir);
                if (copy != null && copy.length > 0) {
                    writeWav(dir.resolve("pre.wav"), copy, copy.length);
                }
                JSONObject meta = new JSONObject();
                meta.put("id", id);
                meta.put("timestamp_ms", now);
                meta.put("timestamp_utc", Instant.ofEpochMilli(now).toString());
                meta.put("engine", engine);
                meta.put("confidence", JSONObject.NULL);
                meta.put("speaker_similarity", JSONObject.NULL);
                meta.put("speaker_threshold", camThr);
                meta.put("livekit_threshold", lkThr);
                meta.put("mic_source", route);
                meta.put("tts_speaking", tts);
                meta.put("wake_latency_ms", -1);
                meta.put("cam_latency_ms", -1);
                meta.put("outcome", "missed_command");
                meta.put("reason", note == null || note.isEmpty() ? "user_missed_command" : note);
                meta.put("user_label", "missed_command");
                meta.put("asr_text", "");
                Files.write(dir.resolve("meta.json"), meta.toString(2).getBytes(StandardCharsets.UTF_8));
                pruneOldest(rootDir(app));
            } catch (Exception ignored) {}
        });
    }

    static void updateAsrTextAsync(Context context, String eventId, String text) {
        if (eventId == null || text == null || !isEnabled(context)) return;
        Context app = context.getApplicationContext();
        IO.execute(() -> updateField(rootDir(app).resolve(eventId).resolve("meta.json"), "asr_text", text));
    }

    static boolean markFalseAlarm(Context context, String eventId) {
        if (eventId == null) return false;
        Path metaFile = rootDir(context).resolve(eventId).resolve("meta.json");
        if (!Files.isRegularFile(metaFile)) return false;
        try {
            JSONObject obj = new JSONObject(new String(Files.readAllBytes(metaFile), StandardCharsets.UTF_8));
            obj.put("user_label", "false_alarm");
            obj.put("outcome", "manual_false_alarm");
            Files.write(metaFile, obj.toString(2).getBytes(StandardCharsets.UTF_8));
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    static String markLastFalseAlarm(Context context) {
        List<Entry> entries = listEvents(context);
        for (Entry e : entries) {
            if (!"missed_command".equals(e.outcome())) {
                if ("false_alarm".equals(e.userLabel())) return "Последняя активация уже отмечена как ложная.";
                return markFalseAlarm(context, e.id())
                        ? "Последняя активация отмечена как ложное срабатывание."
                        : "Не удалось сохранить отметку.";
            }
        }
        return "В журнале пока нет активаций для отметки.";
    }

    static List<Entry> listEvents(Context context) {
        Path root = rootDir(context);
        List<Entry> out = new ArrayList<>();
        if (!Files.isDirectory(root)) return out;
        try (var stream = Files.list(root)) {
            List<Path> dirs = stream.filter(Files::isDirectory).collect(java.util.stream.Collectors.toList());
            for (Path dir : dirs) {
                Path metaFile = dir.resolve("meta.json");
                if (!Files.isRegularFile(metaFile)) continue;
                try {
                    JSONObject obj = new JSONObject(new String(Files.readAllBytes(metaFile), StandardCharsets.UTF_8));
                    out.add(new Entry(
                            obj.optString("id", dir.getFileName().toString()),
                            obj.optLong("timestamp_ms", 0L),
                            obj.optString("timestamp_utc", ""),
                            obj.optString("engine", "unknown"),
                            obj.isNull("confidence") ? Double.NaN : obj.optDouble("confidence", Double.NaN),
                            obj.isNull("speaker_similarity") ? Double.NaN : obj.optDouble("speaker_similarity", Double.NaN),
                            obj.isNull("speaker_threshold") ? Double.NaN : obj.optDouble("speaker_threshold", Double.NaN),
                            obj.isNull("livekit_threshold") ? Double.NaN : obj.optDouble("livekit_threshold", Double.NaN),
                            obj.optString("mic_source", ""),
                            obj.optBoolean("tts_speaking", false),
                            obj.optLong("wake_latency_ms", -1L),
                            obj.optLong("cam_latency_ms", -1L),
                            obj.optString("outcome", ""),
                            obj.optString("reason", ""),
                            obj.optString("user_label", ""),
                            obj.optString("asr_text", ""),
                            Files.isRegularFile(dir.resolve("pre.wav")),
                            Files.isRegularFile(dir.resolve("post.wav"))
                    ));
                } catch (Exception ignored) {}
            }
        } catch (IOException ignored) {}
        out.sort(Comparator.comparingLong(Entry::timestampMs).reversed());
        return out;
    }

    static void exportZip(Context context, Path destZip) throws IOException {
        Path root = rootDir(context);
        List<Entry> entries = listEvents(context);
        JSONArray summary = new JSONArray();
        try (OutputStream fos = Files.newOutputStream(destZip);
             ZipOutputStream zos = new ZipOutputStream(fos)) {
            for (Entry e : entries) {
                Path dir = root.resolve(e.id());
                for (String name : new String[]{"meta.json", "pre.wav", "post.wav"}) {
                    Path f = dir.resolve(name);
                    if (Files.isRegularFile(f)) {
                        zos.putNextEntry(new ZipEntry("events/" + e.id() + "/" + name));
                        Files.copy(f, zos);
                        zos.closeEntry();
                    }
                }
                JSONObject item = new JSONObject();
                try {
                    item.put("id", e.id());
                    item.put("timestamp_utc", e.timestampUtc());
                    item.put("engine", e.engine());
                    item.put("outcome", e.outcome());
                    item.put("reason", e.reason());
                    item.put("user_label", e.userLabel());
                    item.put("confidence", Double.isFinite(e.confidence()) ? e.confidence() : JSONObject.NULL);
                    item.put("speaker_similarity", Double.isFinite(e.speakerSimilarity()) ? e.speakerSimilarity() : JSONObject.NULL);
                    item.put("mic_source", e.micSource());
                    item.put("tts_speaking", e.ttsSpeaking());
                    item.put("wake_latency_ms", e.wakeLatencyMs());
                    item.put("cam_latency_ms", e.camLatencyMs());
                    item.put("asr_text", e.asrText());
                    summary.put(item);
                } catch (Exception ignored) {}
            }
            JSONObject manifest = new JSONObject();
            String manifestJson;
            try {
                manifest.put("version", BuildConfig.VERSION_NAME);
                manifest.put("version_code", BuildConfig.VERSION_CODE);
                manifest.put("event_count", entries.size());
                manifest.put("events", summary);
                manifestJson = manifest.toString(2);
            } catch (Exception ignored) {
                manifestJson = manifest.toString();
            }
            zos.putNextEntry(new ZipEntry("summary.json"));
            zos.write(manifestJson.getBytes(StandardCharsets.UTF_8));
            zos.closeEntry();
        }
    }

    static boolean clearAll(Context context) {
        Path root = rootDir(context);
        if (!Files.exists(root)) return true;
        boolean ok = true;
        try (var walk = Files.walk(root)) {
            List<Path> paths = walk.sorted(Comparator.reverseOrder()).collect(java.util.stream.Collectors.toList());
            for (Path p : paths) {
                if (!p.equals(root)) Files.deleteIfExists(p);
            }
        } catch (IOException e) {
            ok = false;
        }
        try {
            Files.deleteIfExists(context.getCacheDir().toPath().resolve("wileyai-wake-journal.zip"));
        } catch (IOException ignored) {}
        return ok;
    }

    static byte[] wavHeader(int pcmBytes) {
        ByteBuffer buf = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        buf.put("RIFF".getBytes(StandardCharsets.US_ASCII));
        buf.putInt(36 + pcmBytes);
        buf.put("WAVE".getBytes(StandardCharsets.US_ASCII));
        buf.put("fmt ".getBytes(StandardCharsets.US_ASCII));
        buf.putInt(16);
        buf.putShort((short) 1); // PCM
        buf.putShort((short) 1); // Mono
        buf.putInt(SAMPLE_RATE);
        buf.putInt(SAMPLE_RATE * 2);
        buf.putShort((short) 2);
        buf.putShort((short) 16);
        buf.put("data".getBytes(StandardCharsets.US_ASCII));
        buf.putInt(pcmBytes);
        return buf.array();
    }

    private static void writeWav(Path target, short[] pcm, int length) throws IOException {
        ByteBuffer data = ByteBuffer.allocate(44 + length * 2).order(ByteOrder.LITTLE_ENDIAN);
        data.put(wavHeader(length * 2));
        for (int i = 0; i < length; i++) data.putShort(pcm[i]);
        Files.write(target, data.array());
    }

    private static void updateField(Path metaFile, String key, Object val) {
        if (!Files.isRegularFile(metaFile)) return;
        try {
            JSONObject obj = new JSONObject(new String(Files.readAllBytes(metaFile), StandardCharsets.UTF_8));
            obj.put(key, val);
            Files.write(metaFile, obj.toString(2).getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {}
    }

    private static void pruneOldest(Path root) {
        try (var stream = Files.list(root)) {
            List<Path> dirs = stream.filter(Files::isDirectory)
                    .sorted(Comparator.comparing(p -> p.getFileName().toString()))
                    .collect(java.util.stream.Collectors.toList());
            int excess = dirs.size() - MAX_EVENTS;
            for (int i = 0; i < excess; i++) {
                try (var walk = Files.walk(dirs.get(i))) {
                    for (Path p : walk.sorted(Comparator.reverseOrder()).collect(java.util.stream.Collectors.toList())) Files.deleteIfExists(p);
                }
            }
        } catch (IOException ignored) {}
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private WakeActivationJournal() {}
}
