package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
import android.os.SystemClock;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Experimental CAM++ 3D-Speaker owner verification filter (post-wake, zero extra recording).
 *
 * Design invariants:
 * - Off by default (toggleable via {@link #KEY_ENABLED}); Vosk fallback and GigaAM/Silero/PcmHandoff are untouched.
 * - Explicit owner enrollment only ({@link #enroll}); strictly NO automatic learning on live activations or strangers.
 * - Reuses the already-buffered pre-roll PCM window (e.g. 1.5 s ending at wake detection) without opening AudioRecord.
 * - Reaches sherpa-onnx SpeakerEmbeddingExtractor via reflection so builds without the optional AAR still compile cleanly.
 */
final class OwnerSpeakerFilter implements AutoCloseable {
    static final String PREFS = "wiley-mobile";
    static final String KEY_ENABLED = "owner_speaker_filter_enabled";
    static final String KEY_THRESHOLD = "owner_speaker_filter_threshold";
    static final float DEFAULT_THRESHOLD = 0.38f;
    static final float MIN_THRESHOLD = 0.25f;
    static final float MAX_THRESHOLD = 0.70f;
    static final int SAMPLE_RATE = 16000;
    static final int MIN_SAMPLES = 8000; // 0.5 s minimum for stable CAM++ embedding
    private static final String SHERPA = "com.k2fsa.sherpa.onnx.";

    record Result(boolean accepted, float similarity, float threshold, long elapsedUs, String reason) {}

    private final Object extractor;
    private final Method createStream, isReady, compute, releaseExtractor;
    private final Method acceptWaveform, inputFinished, releaseStream;
    private final int dim;
    private boolean closed;

    private OwnerSpeakerFilter(
            Object extractor, Method createStream, Method isReady, Method compute, Method releaseExtractor,
            Method acceptWaveform, Method inputFinished, Method releaseStream, int dim) {
        this.extractor = extractor;
        this.createStream = createStream;
        this.isReady = isReady;
        this.compute = compute;
        this.releaseExtractor = releaseExtractor;
        this.acceptWaveform = acceptWaveform;
        this.inputFinished = inputFinished;
        this.releaseStream = releaseStream;
        this.dim = dim;
    }

    static Path rootDir(Context context) {
        return context.getNoBackupFilesDir().toPath().resolve("owner-speaker");
    }

    static Path profilePath(Context context) {
        return rootDir(context).resolve("profile.json");
    }

    static Path modelPath(Context context) {
        return rootDir(context).resolve("campplus.onnx");
    }

    static boolean isEnabled(Context context) {
        return prefs(context).getBoolean(KEY_ENABLED, false);
    }

    static void setEnabled(Context context, boolean enabled) {
        prefs(context).edit().putBoolean(KEY_ENABLED, enabled).apply();
    }

    static float threshold(Context context) {
        float raw = prefs(context).getFloat(KEY_THRESHOLD, DEFAULT_THRESHOLD);
        return clampThreshold(raw);
    }

    static void setThreshold(Context context, float value) {
        prefs(context).edit().putFloat(KEY_THRESHOLD, clampThreshold(value)).apply();
    }

    static float clampThreshold(float value) {
        if (!Float.isFinite(value)) return DEFAULT_THRESHOLD;
        return Math.max(MIN_THRESHOLD, Math.min(MAX_THRESHOLD, value));
    }

    static boolean hasEnrolledProfile(Context context) {
        try { return loadProfile(context) != null; }
        catch (IOException invalid) { return false; }
    }

    static void clearEnrollment(Context context) throws IOException {
        Files.deleteIfExists(profilePath(context));
    }

    static OwnerSpeakerFilter open(Path modelFile, int threads) throws IOException {
        if (modelFile == null || !Files.isRegularFile(modelFile)) {
            throw new IOException("Модель CAM++ не найдена: " + modelFile);
        }
        try {
            Class<?> cfgType = Class.forName(SHERPA + "SpeakerEmbeddingExtractorConfig");
            Constructor<?> cfgCtor = cfgType.getConstructor(String.class, int.class, boolean.class, String.class);
            Object cfg = cfgCtor.newInstance(modelFile.toAbsolutePath().toString(), Math.max(1, threads), false, "cpu");

            Class<?> extType = Class.forName(SHERPA + "SpeakerEmbeddingExtractor");
            Constructor<?> extCtor = extType.getConstructor(AssetManager.class, cfgType);
            Object extractor = extCtor.newInstance(null, cfg);

            Class<?> streamType = Class.forName(SHERPA + "OnlineStream");
            Method createStream = extType.getMethod("createStream");
            Method isReady = extType.getMethod("isReady", streamType);
            Method compute = extType.getMethod("compute", streamType);
            Method releaseExtractor = extType.getMethod("release");
            int dim = (Integer) extType.getMethod("dim").invoke(extractor);

            Method acceptWaveform = streamType.getMethod("acceptWaveform", float[].class, int.class);
            Method inputFinished = streamType.getMethod("inputFinished");
            Method releaseStream = streamType.getMethod("release");

            return new OwnerSpeakerFilter(
                    extractor, createStream, isReady, compute, releaseExtractor,
                    acceptWaveform, inputFinished, releaseStream, dim);
        } catch (ClassNotFoundException missing) {
            throw new IOException("Нативный движок sherpa-onnx недоступен для CAM++", missing);
        } catch (ReflectiveOperationException | RuntimeException | LinkageError error) {
            throw new IOException("Не удалось инициализировать CAM++ 3D-Speaker", error);
        }
    }

    int embeddingDim() {
        return dim;
    }

    float[] extract(short[] pcm, int length) throws IOException {
        if (pcm == null || length < MIN_SAMPLES) return null;
        int n = Math.min(length, pcm.length);
        float[] samples = new float[n];
        for (int i = 0; i < n; i++) samples[i] = pcm[i] / 32768f;
        return extractFloat(samples);
    }

    float[] extractFloat(float[] samples) throws IOException {
        if (closed) throw new IllegalStateException("OwnerSpeakerFilter is closed");
        if (samples == null || samples.length < MIN_SAMPLES) return null;
        Object stream = null;
        try {
            stream = createStream.invoke(extractor);
            acceptWaveform.invoke(stream, samples, SAMPLE_RATE);
            inputFinished.invoke(stream);
            if (!Boolean.TRUE.equals(isReady.invoke(extractor, stream))) return null;
            float[] raw = (float[]) compute.invoke(extractor, stream);
            return normalize(raw);
        } catch (ReflectiveOperationException | RuntimeException error) {
            throw new IOException("Ошибка вычисления эмбеддинга CAM++", error);
        } finally {
            if (stream != null) {
                try { releaseStream.invoke(stream); } catch (ReflectiveOperationException | RuntimeException ignored) {}
            }
        }
    }

    /**
     * Explicit owner voice enrollment from user-recorded clips.
     * Averages L2-normalized embeddings and saves a single immutable owner reference vector.
     */
    int enroll(Context context, List<short[]> clips) throws IOException {
        if (clips == null || clips.isEmpty()) throw new IOException("Нужны записи голоса владельца");
        float[] sum = null;
        int used = 0;
        for (short[] clip : clips) {
            float[] emb = extract(clip, clip == null ? 0 : clip.length);
            if (emb == null) continue;
            if (sum == null) sum = new float[emb.length];
            if (emb.length != sum.length) continue;
            for (int i = 0; i < emb.length; i++) sum[i] += emb[i];
            used++;
        }
        if (sum == null || used == 0) throw new IOException("Не удалось извлечь эмбеддинг голоса владельца");
        float[] ref = normalize(sum);
        if (ref == null) throw new IOException("Нулевой вектор голоса владельца");
        saveProfile(context, ref, used);
        return used;
    }

    /**
     * Post-wake verification reusing pre-roll audio buffer (no extra microphone capture, no auto-learning).
     */
    Result verify(Context context, short[] preRollPcm, int length) throws IOException {
        float thr = threshold(context);
        if (!isEnabled(context)) {
            return new Result(true, Float.NaN, thr, 0L, "filter_disabled");
        }
        float[] ref = loadProfile(context);
        if (ref == null) {
            return new Result(true, Float.NaN, thr, 0L, "not_enrolled");
        }
        return verifyAgainstReference(ref, preRollPcm, length, thr);
    }

    Result verifyAgainstReference(float[] reference, short[] preRollPcm, int length, float threshold) throws IOException {
        long started = SystemClock.elapsedRealtimeNanos();
        float[] emb = extract(preRollPcm, length);
        long elapsedUs = (SystemClock.elapsedRealtimeNanos() - started) / 1000L;
        if (emb == null) {
            return new Result(false, 0f, threshold, elapsedUs, "audio_too_short");
        }
        float sim = cosine(reference, emb);
        boolean ok = sim >= threshold;
        return new Result(ok, sim, threshold, elapsedUs, ok ? "owner_match" : "speaker_rejected");
    }

    static float[] loadProfile(Context context) throws IOException {
        Path file = profilePath(context);
        if (!Files.isRegularFile(file)) return null;
        try {
            if (Files.size(file) > 32768) return null;
            JSONObject obj = new JSONObject(new String(Files.readAllBytes(file), StandardCharsets.UTF_8));
            JSONArray arr = obj.optJSONArray("embedding");
            if (!"campplus-3d-speaker".equals(obj.optString("model")) || arr == null || arr.length() != 192) return null;
            float[] out = new float[arr.length()];
            for (int i = 0; i < arr.length(); i++) {
                out[i] = (float) arr.getDouble(i);
                if (!Float.isFinite(out[i])) return null;
            }
            return normalize(out);
        } catch (Exception invalid) {
            throw new IOException("Повреждённый профиль голоса владельца", invalid);
        }
    }

    private static void saveProfile(Context context, float[] ref, int sampleCount) throws IOException {
        Path file = profilePath(context);
        Files.createDirectories(file.getParent());
        JSONObject obj = new JSONObject();
        try {
            obj.put("version", 1);
            obj.put("model", "campplus-3d-speaker");
            obj.put("dim", ref.length);
            obj.put("sampleCount", sampleCount);
            obj.put("enrolledAtMs", System.currentTimeMillis());
            JSONArray arr = new JSONArray();
            for (float v : ref) arr.put(v);
            obj.put("embedding", arr);
        } catch (Exception jsonError) {
            throw new IOException("Не удалось сериализовать профиль владельца", jsonError);
        }
        Path pending = Files.createTempFile(file.getParent(), "speaker-profile-", ".part");
        try {
            Files.write(pending, obj.toString().getBytes(StandardCharsets.UTF_8));
            Files.move(pending, file, java.nio.file.StandardCopyOption.ATOMIC_MOVE,
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(pending); }
    }

    static float[] normalize(float[] v) {
        if (v == null || v.length == 0) return null;
        double normSq = 0.0;
        for (float x : v) normSq += (double) x * (double) x;
        if (!(normSq > 0.0) || !Double.isFinite(normSq)) return null;
        float inv = (float) (1.0 / Math.sqrt(normSq));
        float[] out = new float[v.length];
        for (int i = 0; i < v.length; i++) out[i] = v[i] * inv;
        return out;
    }

    static float cosine(float[] a, float[] b) {
        if (a == null || b == null || a.length != b.length) return 0f;
        double dot = 0.0;
        for (int i = 0; i < a.length; i++) dot += (double) a[i] * (double) b[i];
        return (float) dot;
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    @Override public void close() {
        if (closed) return;
        closed = true;
        try { releaseExtractor.invoke(extractor); }
        catch (ReflectiveOperationException | RuntimeException | LinkageError ignored) {}
    }
}
