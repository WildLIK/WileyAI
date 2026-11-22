package ru.wildlik.wileyai.mobile;

import android.content.*;
import android.media.*;
import android.os.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;
import org.json.*;
import org.vosk.Recognizer;

import static ru.wildlik.wileyai.mobile.AcousticStore.*;

/** Opt-in diagnostic subscriber. The existing WakeEngine alone owns and reads AudioRecord. */
final class AcousticDiagnostics {
    static final int RATE = AcousticCapture.RATE;
    static final String[] LABELS = {"Не размечено", "Правильный вызов владельца", "Пропущенный вызов владельца",
            "Ложная активация на речь владельца", "Посторонний голос", "Речь из видео", "Фоновый шум", "Неизвестная причина"};
    static final String[] FORMS = {"Вайли", "Уайли", "Окей, Вайли", "Окей, Уайли", "Слитно с командой", "Обращение с паузой"};
    static final String[] CONDITIONS = {"Рядом", "На расстоянии", "В кармане", "Bluetooth-наушники", "Воспроизводится видео", "Окружающий шум"};
    private static final long MIB = 1024 * 1024;
    private static final int MAX_EVENTS = 180;
    private static volatile AcousticDiagnostics instance;
    private final Context app;
    private final AcousticStore store;
    private final Path playbackCache;
    private final SharedPreferences prefs;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Semaphore blocks = new Semaphore(24);
    private final Semaphore metadata = new Semaphore(64);
    private volatile Run active;
    private volatile String status = "Выключена";
    private boolean analyzing;
    private volatile boolean analysisCancelled;
    private volatile GigaAmSession.Ticket analysisTicket;

    static AcousticDiagnostics current() { return instance; }
    static synchronized AcousticDiagnostics get(Context context) {
        if (instance == null) instance = new AcousticDiagnostics(context.getApplicationContext());
        return instance;
    }
    private AcousticDiagnostics(Context context) { this(context, context.getFilesDir().toPath().resolve("wake-acoustics")); }
    AcousticDiagnostics(Context context, Path directory) {
        app = context;
        store = new AcousticStore(directory);
        playbackCache = context.getCacheDir().toPath().resolve(directory.getFileName() + "-playback");
        prefs = context.getSharedPreferences("wake-acoustics-settings", Context.MODE_PRIVATE);
        io.execute(this::recover);
    }
    private void recover() {
        try {
            AcousticStore.erase(playbackCache);
            for (Path session : children(store.root)) {
                for (Path file : children(session.resolve("events"))) {
                    if (!file.getFileName().toString().endsWith(".json")) continue;
                    JSONObject event = read(file);
                    if (event.optString("audio_error").equals("capture_in_progress")) {
                        set(event, "audio_error", "app_restarted_before_commit");
                        Path raw = session.resolve("audio").resolve(id(event) + ".pcm.part");
                        if (Files.isRegularFile(raw)) {
                            long bytes = Files.size(raw);
                            try {
                                if (bytes > 0 && bytes <= 600L * RATE * 2 && bytes % 2 == 0
                                        && store.reserve(bytes + 131072, limit(), false, session)) {
                                    set(event, "samples", bytes / 2);
                                    set(event, "interruption", "recovered_after_process_restart_without_span_index");
                                    event.remove("audio_error");
                                    store.publishAudio(session, raw, event);
                                }
                            } catch (Exception failure) { set(event, "audio_error", "recovery_io"); }
                        }
                        store.event(session, event);
                    }
                }
                for (Path file : children(session.resolve("audio"))) {
                    if (file.getFileName().toString().endsWith(".part")) Files.deleteIfExists(file);
                }
            }
        } catch (IOException failure) { status = "Не удалось проверить незавершённые файлы"; }
    }

    private static final class Run {
        final String id = UUID.randomUUID().toString();
        final long start = SystemClock.elapsedRealtime(), utc = System.currentTimeMillis();
        final int minutes;
        final String mode;
        final boolean suppress, prune;
        final long limit;
        final Path dir;
        final AcousticCapture audio = new AcousticCapture();
        final ArrayList<Clip> pending = new ArrayList<>(2);
        final JSONArray partial = new JSONArray();
        final Set<Long> acceptedIds = new HashSet<>();
        final String continuousId = "continuous_0001";
        final JSONObject continuousEvent;
        boolean ready;
        long captureId = -1, lastRejected = -10000, nextPartial, lastRoute = -10000, lastStats = -10000;
        long stored, dropped, skippedEvents, skippedMetadata;
        int nextId, events;
        int stageCount, peak, clipped;
        long energy;
        int form, condition;
        String lastPartial = "", routeFingerprint = "", preset = "", grammar = "";
        Runnable deadline;
        long latestInput;
        OutputStream spool;
        long written, lastEnd = -1, lastEpoch = -1;
        final JSONArray spans = new JSONArray();
        volatile boolean storageFault;

        Run(Path root, String mode, int minutes, boolean suppress, int form, int condition, long limit, boolean prune) {
            this.dir = root.resolve(id); this.mode = mode; this.minutes = minutes;
            this.suppress = suppress; this.form = form; this.condition = condition;
            this.limit = limit; this.prune = prune;
            continuousEvent = stamp(utc, start, "id", continuousId, "session_id", id, "kind", "continuous",
                    "audio_error", "capture_in_progress", "label", 0);
        }
        boolean continuous() { return mode.equals("continuous"); }
        Path spool() { return dir.resolve("audio").resolve(continuousId + ".pcm.part"); }
    }
    private record Clip(JSONObject event, AcousticCapture.Window pcm) {}
    interface Work { void run() throws Exception; }

    String status() { return status; }
    boolean active() { return active != null; }
    boolean capturingInput() { return active != null; }
    boolean suppresses() { Run run = active; return run != null && run.suppress; }
    long limit() { return prefs.getInt("limit_mib", 200) * MIB; }
    boolean prune() { return prefs.getBoolean("prune", false); }
    void settings(int mib, boolean prune) {
        prefs.edit().putInt("limit_mib", Math.max(50, Math.min(500, mib))).putBoolean("prune", prune).apply();
    }
    synchronized void start(String mode, int minutes, boolean suppress, int form, int condition) {
        if (active != null || analyzing) return;
        if (!HandsFreeService.running()) { status = "Сначала включите фоновый голосовой вызов"; return; }
        begin(mode, minutes, suppress, form, condition);
    }
    // Package-private for the isolated release instrumentation. Never reads a microphone.
    synchronized void begin(String mode, int minutes, boolean suppress, int form, int condition) {
        if (active != null || analyzing) return;
        Run run = new Run(store.root, mode, minutes, suppress || mode.equals("continuous"), form, condition, limit(), prune());
        active = run;
        status = "Подготовка хранилища";
        io.execute(() -> {
            try {
                Files.createDirectories(store.root);
                long reserve = run.continuous() ? run.minutes * 60L * RATE * 4 + 2 * MIB : 2 * MIB;
                if (!store.reserve(reserve, run.limit, run.prune, run.dir)) {
                    stop(run, "storage_limit");
                    return;
                }
                JSONObject settings = stamp(run.utc, run.start, "session_id", run.id, "mode", run.mode,
                        "minutes", run.minutes, "suppress_wake", run.suppress, "wake_confidence_threshold", WakePhrase.MIN_CONFIDENCE,
                        "audio_source", "VOICE_RECOGNITION", "block_samples", 2048, "pre_roll_samples", AcousticCapture.BEFORE,
                        "post_roll_samples", AcousticCapture.AFTER, "software_filter_on_retained_pcm", "none",
                        "gigaam_automatic_transcription", false);
                store.write(run.dir.resolve("session.json"), settings);
                if (run.continuous()) {
                    Files.createDirectories(run.spool().getParent());
                    run.spool = new BufferedOutputStream(Files.newOutputStream(run.spool()));
                    store.event(run.dir, run.continuousEvent);
                }
                synchronized (this) {
                    if (active != run) return;
                    run.ready = true;
                    status = (run.continuous() ? "Непрерывная" : run.mode.equals("guided") ? "Проверка голоса" : "Пассивная")
                            + " запись · " + run.minutes + " мин" + (run.suppress ? " · окно отключено" : "");
                }
            } catch (IOException failure) { stop(run, "storage_io"); }
        });
        run.deadline = () -> stop(run, "timer");
        main.postDelayed(run.deadline, minutes * 60000L);
        main.post(HandsFreeService::refreshAcousticNotice);
    }
    synchronized void stop(String reason) { if (active != null) stop(active, reason); }
    private synchronized void stop(Run run, String reason) {
        if (active != run) return;
        if (run.deadline != null) { main.removeCallbacks(run.deadline); run.deadline = null; }
        run.ready = false;
        active = null;
        for (Clip clip : run.pending) {
            set(clip.event, "tail_status", reason);
            saveWindow(run, clip);
        }
        run.pending.clear();
        run.audio.reset();
        status = reason.startsWith("storage") ? "Остановлена: лимит или ошибка хранилища" : "Выключена · сохраняю результат";
        long ended = SystemClock.elapsedRealtime();
        io.execute(() -> {
            try {
                if (run.spool != null) {
                    run.spool.close();
                    set(run.continuousEvent, "samples", run.written);
                    set(run.continuousEvent, "spans", run.spans);
                    if (run.written > 0) {
                        run.continuousEvent.remove("audio_error");
                        store.publishAudio(run.dir, run.spool(), run.continuousEvent);
                    } else {
                        set(run.continuousEvent, "audio_error", "no_pcm");
                        Files.deleteIfExists(run.spool());
                    }
                    store.event(run.dir, run.continuousEvent);
                }
                if (Files.isDirectory(run.dir)) store.line(run.dir, "performance", stamp(System.currentTimeMillis(), ended,
                        "session_id", run.id, "kind", "session_stop", "reason", reason,
                        "dropped_pcm_samples", run.dropped + (run.continuous() ? run.stored - run.written : 0),
                        "skipped_candidates", run.skippedEvents, "skipped_metadata", run.skippedMetadata));
                if (active == null && !reason.startsWith("storage")) status = "Выключена · журнал сохранён";
            } catch (Exception failure) {
                if (active == null) status = "Выключена · ошибка сохранения";
            }
        });
        main.post(HandsFreeService::refreshAcousticNotice);
    }

    static boolean capturing() { AcousticDiagnostics self = current(); return self != null && self.active(); }

    synchronized boolean ready() { return active != null && active.ready; }
    synchronized void feed(AudioRecord mic, long captureId, long inputStart, short[] data, int count) {
        feed(mic, captureId, inputStart, data, count, "", "");
    }
    synchronized void feed(AudioRecord mic, long captureId, long inputStart, short[] data, int count, String grammar, String preset) {
        Run run = active;
        if (run == null || !run.ready) return;
        long now = SystemClock.elapsedRealtime();
        if (now - run.start >= run.minutes * 60000L) { stop(run, "timer"); return; }
        if (run.captureId != captureId) {
            flushEpoch(run, "new_capture_epoch");
            run.captureId = captureId;
            run.lastRoute = -10000;
            run.grammar = grammar;
            run.preset = preset;
            if (run.continuous() && !run.continuousEvent.has("preset") && !grammar.isEmpty()) {
                set(run.continuousEvent, "grammar", grammar);
                set(run.continuousEvent, "preset", preset);
            }
            record(run, "performance", stamp(System.currentTimeMillis(), now, "session_id", run.id,
                    "capture_id", Long.toString(captureId), "kind", "capture_started", "first_input_sample", inputStart,
                    "grammar", grammar, "preset", preset));
        }
        run.audio.feed(data, count);
        run.latestInput = inputStart + count;
        if (now - run.lastRoute >= 1000 && mic != null) {
            run.lastRoute = now;
            AcousticEnvironment.sample(this, run, mic, now, captureId);
        }
        measure(run, data, count, now);
        for (Iterator<Clip> iter = run.pending.iterator(); iter.hasNext();) {
            Clip frame = iter.next();
            if (frame.pcm.add(data, count)) { iter.remove(); saveWindow(run, frame); }
        }
        if (!run.continuous()) return;
        if (!blocks.tryAcquire()) { run.dropped += count; return; }
        short[] copy = Arrays.copyOf(data, count);
        run.stored += count;
        io.execute(() -> {
            try {
                if (run.spool == null || run.storageFault) return;
                AcousticAudio.pcm(run.spool, copy, copy.length);
                if (run.lastEpoch != captureId || run.lastEnd != inputStart) {
                    run.spans.put(fields("capture_id", Long.toString(captureId), "input_start", inputStart,
                            "file_start", run.written, "elapsed_ms", now, "grammar", grammar, "preset", preset));
                }
                run.written += copy.length;
                run.lastEnd = inputStart + copy.length;
                run.lastEpoch = captureId;
            } catch (IOException failure) {
                run.storageFault = true;
                stop(run, "storage_io");
            } finally { blocks.release(); }
        });
    }
    private void measure(Run run, short[] data, int n, long now) {
        for (int i = 0; i < n; i++) {
            int sample = data[i], abs = Math.abs(sample);
            run.energy += (long)sample * sample;
            run.peak = Math.max(run.peak, abs);
            if (abs >= 32767) run.clipped++;
        }
        run.stageCount += n;
        if (now - run.lastStats < 1000) return;
        run.lastStats = now;
        record(run, "performance", stamp(System.currentTimeMillis(), now, "session_id", run.id,
                "capture_id", Long.toString(run.captureId), "kind", "pcm_levels", "samples", run.stageCount,
                "rms_pcm16", Math.round(Math.sqrt((double)run.energy / run.stageCount)), "peak_pcm16", run.peak,
                "clipped_samples", run.clipped, "diagnostic_queue_available", blocks.availablePermits()));
        run.energy = 0; run.peak = 0; run.clipped = 0; run.stageCount = 0;
    }
    synchronized void captureEnd(long captureId, int reason) {
        Run run = active;
        if (run == null || !run.ready || run.captureId != captureId) return;
        record(run, "performance", stamp(System.currentTimeMillis(), SystemClock.elapsedRealtime(), "session_id", run.id,
                "capture_id", Long.toString(captureId), "kind", "capture_stopped", "reason", reason,
                "pending_diagnostic_drops", run.dropped));
        flushEpoch(run, "capture_stopped_" + reason);
        run.captureId = -1;
    }
    private void flushEpoch(Run run, String reason) {
        for (Clip clip : run.pending) { set(clip.event, "tail_status", reason); saveWindow(run, clip); }
        run.pending.clear();
        run.audio.reset();
        run.latestInput = 0;
        clearPartial(run);
    }
    private static void clearPartial(Run run) {
        while (run.partial.length() != 0) run.partial.remove(run.partial.length()-1);
        run.lastPartial = "";
        run.nextPartial = 0;
    }

    synchronized void partial(Recognizer decoder, long captureId) {
        Run run = active;
        long now = SystemClock.elapsedRealtime();
        if (run == null || !run.ready || run.captureId != captureId || now < run.nextPartial) return;
        run.nextPartial = now + 250;
        try {
            String hypothesis = new JSONObject(decoder.getPartialResult()).optString("partial");
            if (hypothesis.length() > 180) hypothesis = hypothesis.substring(0, 180);
            if (hypothesis.equals(run.lastPartial)) return;
            run.lastPartial = hypothesis;
            if (run.partial.length() == 32) run.partial.remove(0);
            run.partial.put(fields("elapsed_ms", now, "capture_sample", run.latestInput, "text", hypothesis));
        } catch (Exception unavailable) { /* Diagnostic side path only. */ }
    }

    synchronized boolean candidate(long captureId, WakeActivation wake, String grammar, String phrase,
                                   JSONObject result, String reason, double confidence, long inputSample, long decodeMicros) {
        Run run = active;
        if (run == null) return false;
        if (!run.ready || run.captureId != captureId) return wake != null && run.suppress;
        boolean accepted = wake != null;
        long now = SystemClock.elapsedRealtime();
        if (run.events >= MAX_EVENTS || (!accepted && (now - run.lastRejected < 6000
                || result.optString("text").isBlank() && run.partial.length() == 0))) {
            run.skippedEvents++;
            clearPartial(run);
            return accepted && run.suppress;
        }
        run.events++;
        if (!accepted) run.lastRejected = now;
        else run.acceptedIds.add(wake.id());
        JSONObject event = stamp(System.currentTimeMillis(), now, "id", accepted ? Long.toString(wake.id()) : "wake_" + ++run.nextId,
                "session_id", run.id, "capture_id", Long.toString(captureId), "kind", "candidate", "accepted", accepted,
                "decision", reason, "window_outcome", accepted ? run.suppress ? "suppressed" : "awaiting_numeric_journal" : "not_requested",
                "confidence", Double.isFinite(confidence) ? confidence : null, "capture_sample", inputSample,
                "capture_ms", inputSample * 1000 / RATE, "recognition_us", decodeMicros, "threshold", WakePhrase.MIN_CONFIDENCE,
                "grammar", grammar, "preset", phrase, "variant", accepted ? wake.variant() : null,
                "model_alternatives", result.has("alternatives") ? "present" : "not_enabled_in_production",
                "reported_lag_ms", accepted ? wake.lagMillis() : null, "label", 0);
        if (result.toString().length() <= 8192) set(event, "vosk_final", result);
        else {
            String text = result.optString("text");
            set(event, "vosk_final", fields("text", text.substring(0, Math.min(text.length(), 1024)), "truncated", true));
        }
        try { set(event, "partial", new JSONArray(run.partial.toString())); }
        catch (JSONException ignored) {}
        clearPartial(run);
        if (run.continuous()) link(run, event);
        else {
            AcousticCapture.Window clip = run.audio.mark(true);
            set(event, "source_start", inputSample - (clip.event - clip.start));
            set(event, "tail_requested_samples", AcousticCapture.AFTER);
            if (run.pending.size() < 2) run.pending.add(new Clip(event, clip));
            else {
                set(event, "audio_error", "too_many_pending_clips");
                recordEvent(run, event);
            }
        }
        return accepted && run.suppress;
    }

    synchronized void marker(boolean missed, int form, int condition) {
        Run run = active;
        if (run == null || !run.ready) return;
        if (run.events >= MAX_EVENTS) { run.skippedEvents++; return; }
        run.events++;
        long now = SystemClock.elapsedRealtime();
        JSONObject event = stamp(System.currentTimeMillis(), now, "session_id", run.id,
                "id", (missed ? "missed_" : "test_") + ++run.nextId, "kind", missed ? "missed" : "voice_test",
                "capture_id", run.captureId < 0 ? null : Long.toString(run.captureId), "label", missed ? 2 : 0,
                "capture_sample", run.latestInput, "preset", run.preset, "grammar", run.grammar,
                "form", FORMS[form], "condition", CONDITIONS[condition]);
        record(run, "voice_tests", fields("id", event.optString("id"), "session_id", run.id, "utc", event.optString("utc"),
                "elapsed_ms", now, "kind", event.optString("kind"), "form", FORMS[form], "condition", CONDITIONS[condition]));
        if (run.continuous()) link(run, event);
        else if (missed) {
            AcousticCapture.Window window = run.audio.mark(false);
            set(event, "source_start", run.latestInput - (window.event - window.start));
            saveWindow(run, new Clip(event, window));
        }
        else recordEvent(run, event);
    }
    synchronized void window(long wakeId, String outcome) {
        Run run = active;
        if (run == null || !run.acceptedIds.contains(wakeId) || run.suppress) return;
        JSONObject row = stamp(System.currentTimeMillis(), SystemClock.elapsedRealtime(), "window_outcome", outcome);
        telemetry(run, () -> store.write(run.dir.resolve("windows").resolve(wakeId + ".json"), row));
    }
    private void link(Run run, JSONObject event) {
        set(event, "audio_ref", run.continuousId);
        set(event, "file_event_sample", run.stored);
        long head = Math.max(0, run.stored - Math.min(AcousticCapture.BEFORE, run.audio.position()));
        set(event, "file_start_sample", head);
        set(event, "samples", run.stored - head + (event.optString("kind").equals("candidate") ? AcousticCapture.AFTER : 0));
        recordEvent(run, event);
    }
    private void saveWindow(Run run, Clip clip) {
        JSONObject event = clip.event;
        set(event, "samples", clip.pcm.length);
        set(event, "pre_samples", clip.pcm.event - clip.pcm.start);
        set(event, "post_samples", clip.pcm.length - (clip.pcm.event - clip.pcm.start));
        if (!event.has("tail_status")) set(event, "tail_status", clip.pcm.length == clip.pcm.samples.length ? "complete" : "short");
        if (clip.pcm.length == 0 || !blocks.tryAcquire()) {
            set(event, "audio_error", clip.pcm.length == 0 ? "no_pcm" : "queue_full");
            recordEvent(run, event);
            return;
        }
        io.execute(() -> {
            Path temp = run.dir.resolve("audio").resolve(id(event) + ".pcm.part");
            try {
                if (!store.reserve(clip.pcm.length * 4L + 65536, run.limit, run.prune, run.dir)) {
                    set(event, "audio_error", "storage_limit");
                    stop(run, "storage_limit");
                } else {
                    Files.createDirectories(temp.getParent());
                    try (OutputStream out = Files.newOutputStream(temp)) { AcousticAudio.pcm(out, clip.pcm.samples, clip.pcm.length); }
                    store.publishAudio(run.dir, temp, event);
                }
            } catch (Exception failure) {
                set(event, "audio_error", "storage_io");
                stop(run, "storage_io");
            } finally {
                try { Files.deleteIfExists(temp); store.event(run.dir, event); }
                catch (IOException ignored) {}
                blocks.release();
            }
        });
    }
    private void recordEvent(Run run, JSONObject event) {
        telemetry(run, () -> store.event(run.dir, event));
    }
    private void record(Run run, String series, JSONObject entry) {
        telemetry(run, () -> store.line(run.dir, series, entry));
    }
    private void telemetry(Run run, Work operation) {
        if (!metadata.tryAcquire()) { run.skippedMetadata++; return; }
        io.execute(() -> {
            try { operation.run(); }
            catch (Exception failure) { stop(run, "storage_io"); }
            finally { metadata.release(); }
        });
    }

    private static final class AcousticEnvironment {
        static void sample(AcousticDiagnostics self, Run run, AudioRecord mic, long elapsed, long captureId) {
            long utc = System.currentTimeMillis();
            int records = VoiceTelemetry.snapshot().captureCount();
            self.telemetry(run, () -> {
                JSONObject data = stamp(utc, elapsed, "session_id", run.id, "capture_id", Long.toString(captureId),
                        "record_count", records);
                AcousticRoute.fill(self.app, mic, data);
                String fingerprint = data.optString("input_type") + ":" + data.optString("input_id") + ":" + data.optString("media_active")
                        + ":" + data.optString("media_volume") + ":" + data.optString("output_route") + ":" + data.optString("wiley_tts")
                        + ":" + data.optString("effects_observed") + ":" + data.optString("silenced") + ":" + data.optString("media_app");
                if (!fingerprint.equals(run.routeFingerprint)) {
                    run.routeFingerprint = fingerprint;
                    self.store.line(run.dir, "audio_route", data);
                }
            });
        }
    }

    void list(Consumer<List<JSONObject>> callback) {
        io.execute(() -> {
            List<JSONObject> events;
            try { events = withLegacyLabels(); }
            catch (Exception failure) { events = List.of(); }
            List<JSONObject> saved = events;
            main.post(() -> callback.accept(saved));
        });
    }
    private List<JSONObject> withLegacyLabels() throws Exception {
        List<JSONObject> events = store.events();
        Set<String> marked = new HashSet<>();
        for (String row : DiagnosticLog.acousticRows()) {
            String[] parts = row.split("\\|");
            if (parts.length == 5 && parts[2].equals("WAKE_FALSE_MARK")) marked.add(parts[4]);
        }
        for (JSONObject row : events) if (!row.optBoolean("label_override") && marked.contains(id(row))) {
            set(row, "legacy_false_mark", true);
            set(row, "label", 7);
        }
        for (JSONObject row : events) {
            Path path = store.session(row.optString("session_id")).resolve("windows").resolve(id(row) + ".json");
            if (!Files.isRegularFile(path)) continue;
            JSONObject outcome = read(path);
            set(row, "window_outcome", outcome.optString("window_outcome"));
            set(row, "window_elapsed_ms", outcome.optLong("elapsed_ms"));
        }
        return events;
    }
    void relabel(JSONObject event, int label, String comment, Consumer<String> done) {
        task(() -> {
            set(event, "label", label);
            set(event, "label_override", true);
            set(event, "comment", comment.substring(0, Math.min(240, comment.length())));
            store.event(store.session(event.optString("session_id")), event);
        }, "Метка сохранена", done);
    }
    void remove(JSONObject event, Consumer<String> done) { task(() -> store.remove(event), "Событие удалено", done); }
    void clear(Consumer<String> done) {
        stop("clear");
        cancelAnalysis();
        task(() -> {
            AcousticStore.erase(store.root);
            AcousticStore.erase(playbackCache);
        }, "Диагностические файлы удалены", done);
    }
    void export(UriSupplier output, Consumer<String> done) {
        task(() -> {
            try (OutputStream out = output.open()) {
                if (out == null) throw new IOException("Не удалось открыть файл");
                store.export(out, withLegacyLabels(), DiagnosticLog.acousticRows(), limit(), prune());
            }
        }, "ZIP сохранён", done);
    }
    interface UriSupplier { OutputStream open() throws IOException; }
    private void task(Work operation, String success, Consumer<String> done) {
        io.execute(() -> {
            String result;
            try { operation.run(); result = success; }
            catch (Exception failure) { result = "Операция не завершена. Проверьте данные и свободное место."; }
            String message = result;
            main.post(() -> done.accept(message));
        });
    }
    void openAudio(JSONObject event, Consumer<Path> result) {
        io.execute(() -> {
            Path path;
            try { path = store.audio(event); } catch (IOException missing) { path = null; }
            Path saved = path;
            main.post(() -> result.accept(saved));
        });
    }

    void preparePlayback(JSONObject event, Consumer<Path> result) {
        io.execute(() -> {
            Path file = null;
            try {
                Path source = store.audio(event);
                Files.createDirectories(playbackCache);
                file = Files.createTempFile(playbackCache, "preview-", ".wav");
                AcousticAudio.playbackWav(source, file, event.optLong("file_start_sample"), event.optInt("samples"));
            } catch (IOException failure) {
                deletePreview(file);
                file = null;
            }
            Path ready = file;
            main.post(() -> result.accept(ready));
        });
    }

    void closePlayback(Path file) {
        if (file != null) io.execute(() -> deletePreview(file));
    }

    private void deletePreview(Path file) {
        if (file == null || !playbackCache.equals(file.getParent())) return;
        try { Files.deleteIfExists(file); }
        catch (IOException ignored) { /* Private cache is cleared when diagnostics next initializes. */ }
    }

    synchronized void analyze(JSONObject event, boolean gigaam, Consumer<String> done) {
        if (active != null || analyzing || HandsFreeService.answering()) { done.accept("Завершите запись или текущий голосовой запрос"); return; }
        if (event.optString("kind").equals("continuous")) { done.accept("Для длинной записи используйте метку или повторный прогон на ПК"); return; }
        analyzing = true;
        analysisCancelled = false;
        io.execute(() -> {
            Path session = store.session(event.optString("session_id"));
            long elapsed = SystemClock.elapsedRealtime();
            JSONObject outcome;
            String key = gigaam ? "gigaam" : "vosk_replay";
            try {
                Path path = store.audio(event);
                int count = Math.min(11 * RATE, event.optInt("samples", 0));
                short[] clip = AcousticAudio.read(path, event.optLong("file_start_sample", 0), count);
                if (clip.length == 0) throw new IOException("no_pcm");
                if (HandsFreeService.answering() || analysisCancelled) throw new CancellationException();
                if (gigaam) {
                    float[] samples = new float[clip.length];
                    for (int i = 0; i < samples.length; i++) samples[i] = clip[i] / 32768f;
                    GigaAmSession.Ticket ticket = GigaAmRuntime.get(app).recognize(samples, RATE, clip.length * 1000.0 / RATE);
                    analysisTicket = ticket;
                    if (analysisCancelled) ticket.cancel();
                    try {
                        GigaAmSession.Output output = ticket.result.get(35, TimeUnit.SECONDS);
                        GigaAmSession.Metrics timings = output.metrics();
                        outcome = fields("status", output.stopped() ? "cancelled" : "ok", "text", output.text(),
                                "decode_ms", timings.decodeMs(), "load_ms", timings.loadMs());
                    } catch (TimeoutException timeout) { ticket.cancel(); throw timeout; }
                    finally { analysisTicket = null; }
                } else {
                    outcome = AcousticReplay.vosk(app, clip, event, () -> analysisCancelled);
                }
                set(outcome, "samples", clip.length);
            } catch (CancellationException stopped) {
                outcome = fields("status", "cancelled");
            } catch (Exception | LinkageError problem) {
                outcome = fields("status", "error", "error", problem.getClass().getSimpleName());
            }
            set(outcome, "elapsed_ms", SystemClock.elapsedRealtime() - elapsed);
            set(outcome, "utc", java.time.Instant.now().toString());
            String message = outcome.optString("status").equals("ok") ? "Анализ сохранён" : "Анализ не завершён";
            try {
                JSONObject currentEvent = read(session.resolve("events").resolve(id(event) + ".json"));
                set(currentEvent, key, outcome);
                JSONArray history = currentEvent.optJSONArray("analysis_runs");
                if (history == null) history = new JSONArray();
                if (history.length() >= 12) history.remove(0);
                history.put(fields("run_id", UUID.randomUUID().toString(), "engine", key, "result", outcome));
                set(currentEvent, "analysis_runs", history);
                store.event(session, currentEvent);
            } catch (IOException failure) { message = "Не удалось сохранить анализ"; }
            synchronized (this) { analyzing = false; }
            String result = message;
            main.post(() -> done.accept(result));
        });
    }
    void cancelAnalysis() {
        analysisCancelled = true;
        GigaAmSession.Ticket current = analysisTicket;
        if (current != null) current.cancel();
    }
}
