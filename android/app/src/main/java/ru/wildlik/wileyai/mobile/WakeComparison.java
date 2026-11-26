package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.media.AudioDeviceInfo;
import android.media.AudioRecord;
import android.os.Debug;
import android.os.PowerManager;
import android.os.SystemClock;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.json.JSONObject;

import static ru.wildlik.wileyai.mobile.AcousticStore.*;

final class WakeComparison {
    static final String SHA = "b093a1858d3f671c9ffaf129e9a39868e657a160f150a6749540d422bbbf74cd";
    private static final long LIMIT = 512L * 1024 * 1024;
    private static final int BLOCK = WakeComparisonPcm.BLOCK, RATE = WakeComparisonPcm.RATE;
    static native long open(String model);
    static native boolean reset(long handle);
    static native float score(long handle, short[] pcm);
    static native void close(long handle);
    private static volatile WakeComparison running;
    private static volatile String status = "Выключено";
    private static final String[] FILES = {"session.json", "timeline.jsonl", "audio.flac", "labels.json"};

    record VoskFinal(boolean exact, boolean prefix, double confidence, double prefixConfidence, String reason) {}
    private static final class Packet {
        final short[] pcm = new short[2048];
        long capture, start, time, voskUs, voskCpu;
        int count, source, route, captures;
        boolean interactive;
        VoskFinal decision;
    }
    private record Position(long capture, long end) {}
    record Event(String id, long capture, long end, long elapsedMs, String kind, String description) {}

    private final Context app;
    private final Path dir;
    private final long limitMs;
    private final boolean audio;
    private final String condition;
    private final long started = SystemClock.elapsedRealtime();
    private final long utc = System.currentTimeMillis();
    private final ArrayBlockingQueue<Packet> pool = new ArrayBlockingQueue<>(24);
    private final ArrayBlockingQueue<Packet> pending = new ArrayBlockingQueue<>(24);
    private final ArrayBlockingQueue<JSONObject> annotations = new ArrayBlockingQueue<>(128);
    private final Deque<Event> recent = new ArrayDeque<>();
    private final WakeComparisonPcm frames = new WakeComparisonPcm();
    private final WakeComparisonPcm.Decision decision = new WakeComparisonPcm.Decision();
    private final PowerManager power;
    private volatile String stop;
    private volatile boolean ready;
    private volatile long dropped, offered, received, windows, firstInputMs = -1, lastInputMs = -1;
    private volatile Position lastPosition;
    private long spanStart, spanAudioOffset, spanScoredEnd, spanFirstMs, spanLastMs;
    private volatile String counts = "";
    private long nativeHandle, resets, written, discarded, lastWorkerSample, workerEpoch = -1, sampleEnd;
    private long totalVoskCpu, totalVoskUs, totalLiveCpu, totalLiveUs, maxLiveUs, ticks, serial;
    private int exact, prefixOnly, live, peakCapture, lastSource = -1, lastRoute = -2;
    private boolean lastInteractive;
    private BufferedWriter timeline;
    private OutputStream spool;

    private WakeComparison(Context app, int minutes, boolean audio, String condition) {
        this.app = app.getApplicationContext();
        this.dir = root(app).resolve(UUID.randomUUID().toString());
        this.limitMs = minutes * 60000L;
        this.audio = audio;
        this.condition = condition;
        this.power = app.getSystemService(PowerManager.class);
        for (int i = 0; i < 24; i++) pool.add(new Packet());
    }

    static Path root(Context app) { return app.getNoBackupFilesDir().toPath().resolve("wake-next16"); }
    static synchronized boolean start(Context context, int minutes, boolean audio, String condition) {
        if (running != null) return false;
        var previous = AcousticDiagnostics.current();
        if ((previous != null && previous.active()) || H2Shadow.active()) {
            status = "Остановите другую акустическую диагностику";
            return false;
        }
        String preset = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE)
                .getString("wake_phrase", WakeSettings.defaultPhrase(context));
        if (!WakePhrase.SHORT.equals(preset) || !HandsFreeService.running()
                || !VoiceTelemetry.snapshot().wakeCaptureActive()) {
            status = "Нужен активный фоновый вызов с фразой «Вайли»";
            return false;
        }
        if (minutes != 5 && minutes != 30 && minutes != 60) return false;
        running = new WakeComparison(context, minutes, audio, condition);
        status = "Проверяю модель и хранилище";
        new Thread(running::run, "WakeComparison").start();
        return true;
    }
    static boolean active() { return running != null; }
    static WakeComparison forBlock(String phrase) {
        WakeComparison current = running;
        if (current == null || current.stop != null) return null;
        if (WakePhrase.SHORT.equals(phrase)) return current;
        current.stop = "preset_changed";
        return null;
    }
    static void stop(String reason) {
        WakeComparison current = running;
        if (current != null) current.stop = reason;
    }
    static String status() {
        WakeComparison current = running;
        return current == null || !current.ready ? status
                : "Сравнение · " + current.windows + " окон · " + current.counts
                + " · потеря " + current.dropped + " сэмплов";
    }
    static List<Event> recent() {
        WakeComparison current = running;
        if (current == null) return List.of();
        synchronized (current.recent) { return new ArrayList<>(current.recent); }
    }
    static boolean mark(String kind, String id, String label) {
        WakeComparison current = running;
        Position point = current == null ? null : current.lastPosition;
        return point != null && current.ready && current.stop == null
                && current.annotations.offer(fields("type", kind, "ref", id, "label", label,
                "capture", point.capture(), "sample", point.end(), "ms", current.elapsed()));
    }

    synchronized void offer(AudioRecord mic, long capture, long start, short[] source, int count, VoskFinal result,
               long voskUs, long voskCpu, String grammar) {
        if (!ready || stop != null) return;
        long time = elapsed();
        if (firstInputMs < 0) firstInputMs = time;
        lastInputMs = time;
        lastPosition = new Position(capture, start + count);
        offered += count;
        Packet packet = pool.poll();
        if (packet == null) { dropped += count; return; }
        packet.capture = capture;
        packet.start = start;
        packet.count = count;
        packet.time = time;
        packet.voskUs = voskUs;
        packet.voskCpu = voskCpu;
        packet.decision = result;
        packet.interactive = power != null && power.isInteractive();
        packet.captures = VoiceTelemetry.snapshot().captureCount();
        packet.source = mic.getAudioSource();
        packet.route = -1;
        try {
            AudioDeviceInfo device = mic.getRoutedDevice();
            if (device != null) packet.route = device.getType();
        } catch (RuntimeException unavailable) { /* Route metadata is optional. */ }
        lastGrammar = grammar;
        System.arraycopy(source, 0, packet.pcm, 0, count);
        if (!pending.offer(packet)) { dropped += count; pool.offer(packet); }
    }
    private volatile String lastGrammar;
    private long elapsed() { return SystemClock.elapsedRealtime() - started; }

    private void run() {
        Path raw = dir.resolve("audio.pcm.part");
        Path tmp = dir.resolve("audio.flac.part");
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND);
            Files.createDirectories(root(app));
            long required = audio ? limitMs * RATE * 4 / 1000 + 4_000_000 : 4_000_000;
            long occupied;
            try (var files = Files.walk(root(app))) {
                occupied = files.filter(Files::isRegularFile).mapToLong(file -> file.toFile().length()).sum();
            }
            if (occupied + required > LIMIT || dir.getParent().toFile().getUsableSpace() < required + 30_000_000)
                throw new IOException("storage");
            System.loadLibrary("wiley_livekit_compare");
            long modelBegin = elapsed();
            nativeHandle = open(verifiedModel(app).toString());
            if (nativeHandle == 0) throw new IllegalStateException("ORT init");
            long initMs = elapsed() - modelBegin;
            Files.createDirectories(dir);
            timeline = Files.newBufferedWriter(dir.resolve("timeline.jsonl"), StandardCharsets.UTF_8);
            if (audio) spool = new BufferedOutputStream(Files.newOutputStream(raw), 65536);
            line(fields("type", "start", "ms", elapsed(), "model_load_ms", initMs));
            ready = true;
            while (working()) {
                Packet packet = pending.poll(80, TimeUnit.MILLISECONDS);
                if (packet != null) {
                    consume(packet);
                    pool.offer(packet);
                }
                if (!HandsFreeService.running() && stop == null) stop = "service_stopped";
                flushMarks();
                if (elapsed() / 5000 > ticks) {
                    ticks = elapsed() / 5000;
                    line(fields("type", "progress", "ms", elapsed(), "received", received,
                            "processed_windows", windows, "queue_dropped", dropped,
                            "pss_kib", Debug.getPss(), "captures", peakCapture));
                    timeline.flush();
                }
            }
            ready = false;
            finishSpan();
            flushMarks();
            if (spool != null) {
                spool.close();
                spool = null;
                if (written > 0) {
                    AcousticAudio.encodeComparisonFlac(raw, tmp);
                    Files.move(tmp, dir.resolve("audio.flac"));
                }
            }
            line(fields("type", "stop", "ms", elapsed(), "reason", stop));
        } catch (IOException error) {
            stop = "storage_or_asset";
        } catch (Exception | LinkageError | OutOfMemoryError error) {
            stop = "inference_or_runtime";
        } finally {
            ready = false;
            if (nativeHandle != 0) close(nativeHandle);
            closeQuietly(spool);
            closeQuietly(timeline);
            try {
                Files.deleteIfExists(raw);
                Files.deleteIfExists(tmp);
                if (Files.isDirectory(dir)) {
                    JSONObject report = stamp(utc, started, "schema", 1, "session", dir.getFileName().toString(),
                            "mode", "NEXT16", "condition", condition, "reason", stop, "duration_ms", elapsed(),
                            "recording_consent", audio, "audio_samples", written, "offered_samples", offered,
                            "received_samples", received, "queue_dropped_samples", dropped,
                            "unprocessed_samples", Math.max(0, offered - dropped - received),
                            "livekit_samples", windows * BLOCK,
                            "livekit_unscored_tail_samples", discarded + frames.pending(),
                            "livekit_windows", windows, "livekit_reset_count", resets,
                            "max_audio_records_wakeai", peakCapture, "first_pcm_ms", firstInputMs,
                            "last_pcm_ms", lastInputMs, "vosk_cpu_us", totalVoskCpu, "vosk_wall_us", totalVoskUs,
                            "livekit_cpu_us", totalLiveCpu, "livekit_wall_us", totalLiveUs,
                            "livekit_max_block_us", maxLiveUs, "vosk", exact, "next12_only", prefixOnly, "livekit", live,
                            "model_sha256", SHA, "block_samples", BLOCK, "threshold", .99,
                            "consecutive", 2, "rearm_samples", WakeComparisonPcm.Decision.REARM,
                            "vosk_min_confidence", WakePhrase.MIN_CONFIDENCE, "vosk_grammar", lastGrammar,
                            "package_version", BuildConfig.VERSION_NAME);
                    new AcousticStore(root(app)).write(dir.resolve("session.json"), report);
                }
            } catch (IOException error) { stop = "storage_or_asset"; }
            synchronized (WakeComparison.class) {
                status = "Завершено · " + stop + " · " + windows + " окон · " + counts;
                running = null;
            }
        }
    }

    private synchronized boolean working() {
        if (stop == null && elapsed() >= limitMs) stop = "limit";
        return stop == null || !pending.isEmpty();
    }

    private void finishSpan() throws IOException {
        if (workerEpoch != -1) line(fields("type", "span", "capture", workerEpoch,
                "sample", spanStart, "end_sample", lastWorkerSample, "scored_end", spanScoredEnd,
                "audio_offset", spanAudioOffset, "first_ms", spanFirstMs, "last_ms", spanLastMs));
    }

    private void consume(Packet packet) throws IOException {
        received += packet.count;
        peakCapture = Math.max(peakCapture, packet.captures);
        boolean newSpan = frames.discontinuity(packet.capture, packet.start);
        if (newSpan) {
            finishSpan();
            if (resets > 0 && !reset(nativeHandle)) throw new IllegalStateException("ORT reset");
            decision.reset();
            resets++;
            spanStart = spanScoredEnd = packet.start;
            spanAudioOffset = written;
            spanFirstMs = Math.max(0, packet.time - packet.count * 1000L / RATE);
            line(fields("type", "reset", "capture", packet.capture, "sample", packet.start, "ms", packet.time,
                    "missing_samples", workerEpoch == packet.capture ? Math.max(0, packet.start - lastWorkerSample) : 0,
                    "audio_offset", written));
        }
        if (newSpan || packet.interactive != lastInteractive || packet.source != lastSource || packet.route != lastRoute) {
            line(fields("type", "route", "capture", packet.capture, "sample", packet.start, "ms", packet.time,
                    "interactive", packet.interactive, "source", packet.source, "input_type", packet.route,
                    "active_wiley_audio_records", packet.captures));
        }
        spanLastMs = packet.time;
        lastInteractive = packet.interactive;
        lastRoute = packet.route;
        lastSource = packet.source;
        workerEpoch = packet.capture;
        sampleEnd = packet.start + packet.count;
        lastWorkerSample = sampleEnd;
        if (spool != null) {
            AcousticAudio.pcm(spool, packet.pcm, packet.count);
            written += packet.count;
        }
        totalVoskUs += packet.voskUs;
        totalVoskCpu += packet.voskCpu;
        VoskFinal result = packet.decision;
        if (result != null) {
            if (result.exact()) exact++;
            if (result.prefix()) prefixOnly++;
            emit(packet, sampleEnd, "vosk_final", result.reason(), result.confidence(), packet.voskUs,
                    "vosk", result.exact(), "next12", result.exact() || result.prefix(),
                    "prefix_confidence", finite(result.prefixConfidence()));
        }
        try {
            WakeComparisonPcm.Change change = frames.append(packet.capture, packet.start, packet.pcm, packet.count, (end, samples) -> {
                long began = SystemClock.elapsedRealtimeNanos(), cpu = Debug.threadCpuTimeNanos();
                float probability = score(nativeHandle, samples);
                long wallUs = (SystemClock.elapsedRealtimeNanos() - began) / 1000;
                totalLiveCpu += (Debug.threadCpuTimeNanos() - cpu) / 1000;
                totalLiveUs += wallUs;
                maxLiveUs = Math.max(wallUs, maxLiveUs);
                if (!Float.isFinite(probability)) throw new IllegalStateException("ORT score");
                windows++;
                spanScoredEnd = end;
                if (decision.update(end, probability)) {
                    live++;
                    try { emit(packet, end, "livekit", "accepted", probability, wallUs, "queue_us",
                            Math.max(0, elapsed() - packet.time) * 1000); }
                    catch (IOException error) { throw new UncheckedIOException(error); }
                }
            });
            discarded += change.abandoned();
        } catch (UncheckedIOException error) { throw error.getCause(); }
        counts = "Vosk " + exact + " · NEXT 12 " + (exact + prefixOnly) + " · LiveKit " + live;
    }

    private static Object finite(double number) { return Double.isFinite(number) ? number : JSONObject.NULL; }
    private void emit(Packet p, long end, String kind, String detail, double confidence, long usec, Object... extra)
            throws IOException {
        String id = Long.toString(++serial);
        long eventTime = Math.max(0, p.time - (p.start + p.count - end) * 1000 / RATE);
        JSONObject row = fields("type", kind, "id", id, "capture", p.capture, "end_sample", end, "ms", eventTime,
                "score", finite(confidence), "reason", detail, "processing_us", usec, "interactive", p.interactive,
                "source", p.source, "input_type", p.route);
        for (int i = 0; i < extra.length; i += 2) set(row, (String) extra[i], extra[i + 1]);
        line(row);
        if (kind.equals("livekit") || row.optBoolean("next12")) {
            String engines = kind.equals("livekit") ? "LiveKit C" : row.optBoolean("vosk") ? "Vosk + NEXT 12" : "NEXT 12";
            Event event = new Event(id, p.capture, end, eventTime, kind,
                    String.format(Locale.ROOT, "%s · %.2f с · score %.3f", engines, eventTime / 1000.0,
                            detail.equals("final_prefix") ? row.optDouble("prefix_confidence") : confidence));
            synchronized (recent) {
                recent.addFirst(event);
                if (recent.size() > 24) recent.removeLast();
            }
        }
    }

    private void flushMarks() throws IOException {
        for (JSONObject row; (row = annotations.poll()) != null;) line(row);
    }

    private void line(JSONObject row) throws IOException {
        timeline.write(row.toString());
        timeline.newLine();
    }

    private static void closeQuietly(Closeable object) {
        if (object != null) try { object.close(); } catch (IOException ignored) {}
    }

    static Path verifiedModel(Context app) throws Exception {
        Path file = app.getCacheDir().toPath().resolve("wake-next16.onnx");
        Path candidate = Files.createTempFile(file.getParent(), "wake-next16", ".part");
        try (InputStream input = app.getAssets().open("wake-next16/C.onnx")) {
            Files.copy(input, candidate, StandardCopyOption.REPLACE_EXISTING);
            StringBuilder digest = new StringBuilder();
            MessageDigest hash = MessageDigest.getInstance("SHA-256");
            try (InputStream model = Files.newInputStream(candidate)) {
                byte[] block = new byte[32768];
                for (int count; (count = model.read(block)) != -1;) hash.update(block, 0, count);
            }
            for (byte value : hash.digest()) digest.append(String.format(Locale.ROOT, "%02x", value));
            if (!SHA.contentEquals(digest)) throw new IOException("Model checksum");
            Files.move(candidate, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            return file;
        } finally { Files.deleteIfExists(candidate); }
    }

    static void export(Path session, OutputStream output) throws IOException {
        if (output == null) throw new IOException("No output");
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            zip.setLevel(0);
            for (String name : FILES) {
                Path file = session.resolve(name);
                if (!Files.isRegularFile(file)) continue;
                zip.putNextEntry(new ZipEntry(name));
                Files.copy(file, zip);
                zip.closeEntry();
            }
        }
    }
}
