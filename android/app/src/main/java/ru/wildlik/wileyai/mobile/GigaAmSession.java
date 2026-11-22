package ru.wildlik.wileyai.mobile;

import java.io.IOException;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** One process-wide owner of the GigaAM recognizer. Only the worker touches native resources, except atomic abort. */
final class GigaAmSession implements AutoCloseable {
    static final long LOAD_RESERVE = 550L * 1024 * 1024;
    interface Backend {
        long create(String encoder, String decoder, String joiner, String tokens, int threads) throws IOException;
        String decode(long handle, float[] samples, int sampleRate) throws IOException;
        void close(long handle);
    }
    interface MemoryReader { Memory read() throws IOException; }
    record Memory(long available, long total, boolean low) {
        boolean sufficient() { return !low && available >= LOAD_RESERVE; }
    }
    record Model(String identity, String encoder, String decoder, String joiner, String tokens) {}
    record Metrics(boolean cold, String result, long loads, long loadAttempts, long unloads,
                   String unloadReason, double loadMs, double decodeMs, double queueMs,
                   double totalMs, double audioMs, double rtf, long ramBefore, long ramAfter) {
        String safeLine() {
            return "cold=" + cold + " result=" + result + " loads=" + loads + " attempts=" + loadAttempts +
                " unloads=" + unloads + " unload_reason=" + unloadReason + " load_ms=" + loadMs +
                " decode_ms=" + decodeMs + " queue_ms=" + queueMs + " total_ms=" + totalMs +
                " audio_ms=" + audioMs + " rtf=" + rtf + " ram_before=" + ramBefore + " ram_after=" + ramAfter;
        }
    }
    record Output(String text, boolean stopped, Metrics metrics) {}
    final class Ticket {
        final CompletableFuture<Output> result = new CompletableFuture<>();
        final AtomicBoolean cancelled = new AtomicBoolean();
        final long submitted = System.nanoTime(), version;
        Ticket(long version) { this.version = version; }
        public void cancel() { abort(this); }
    }
    private final Backend backend;
    private final MemoryReader memory;
    private final Consumer<Metrics> observer;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(r -> daemon(r, "wiley-gigaam"));
    private final ScheduledThreadPoolExecutor timer = new ScheduledThreadPoolExecutor(1, r -> daemon(r, "wiley-gigaam-timer"));
    private final Object gate = new Object();
    private long handle, version, idleVersion, loads, attempts, unloads, finishedAt;
    private long idleMillis;
    private int pending;
    private Model loaded;
    private String desired = "", evict = "", lastUnload = "none";
    private Ticket active;
    private ScheduledFuture<?> idle;
    private boolean closed;
    private volatile Metrics latest;
    GigaAmSession(Backend backend, MemoryReader memory, long idleMillis, Consumer<Metrics> observer) {
        this.backend = backend; this.memory = memory; this.idleMillis = idleMillis; this.observer = observer;
        timer.setRemoveOnCancelPolicy(true); timer.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
    }
    private static Thread daemon(Runnable r, String name) { Thread t = new Thread(r, name); t.setDaemon(true); return t; }
    private static double ms(long nanos) { return Math.round(nanos / 10000.0) / 100.0; }
    Metrics latest() { return latest; }
    Ticket recognize(Model model, float[] samples, int sampleRate, double audioMs) {
        Ticket ticket;
        synchronized (gate) {
            ticket = new Ticket(version);
            if (closed || pending >= 4) { ticket.result.completeExceptionally(new IOException(closed ? "Движок распознавания закрыт" : "Очередь распознавания занята")); return ticket; }
            if (!desired.equals(model.identity())) { desired = model.identity(); version++; if (active != null) abort(active); }
            ticket = new Ticket(version); Ticket admitted = ticket;
            cancelIdle(); pending++;
            worker.execute(() -> decode(admitted, model, samples, sampleRate, audioMs));
            return admitted;
        }
    }
    private void check(Ticket t) {
        synchronized (gate) { if (closed || t.cancelled.get() || t.version != version) throw new CancellationException(); }
    }
    private void abort(Ticket t) {
        // The blocking decode finishes and its result is dropped; the weights stay warm for the next try.
        synchronized (gate) { t.cancelled.set(true); }
    }
    private void decode(Ticket t, Model model, float[] samples, int sampleRate, double audioMs) {
        long started = System.nanoTime(), load = 0, decode = 0, before = -1, after = -1;
        boolean cold = false, used = false, stopped = false, poisoned = false;
        String text = ""; Throwable error = null;
        ScheduledFuture<?> deadline = null;
        try {
            check(t); synchronized (gate) { active = t; }
            // The JNI decode cannot be interrupted; an expired or cancelled ticket only abandons the result.
            deadline = timer.schedule(t::cancel, 30, TimeUnit.SECONDS);
            if (loaded != null && !loaded.identity().equals(model.identity())) unload("model_changed");
            Memory info = memory.read(); before = info.available();
            if (!info.sufficient()) { unload("memory_before"); throw new IOException("Сейчас мало свободной памяти для распознавания GigaAM. Используйте текущий распознаватель или закройте тяжёлые приложения."); }
            check(t); cold = loaded == null;
            if (cold) {
                used = true;
                long began = System.nanoTime(); attempts++;
                long created = backend.create(model.encoder(), model.decoder(), model.joiner(), model.tokens(), GigaAmModel.THREADS);
                if (created == 0) throw new IOException("Не удалось создать распознаватель GigaAM");
                synchronized (gate) { handle = created; }
                try { check(t); } finally { load = System.nanoTime() - began; }
                synchronized (gate) { loaded = model; loads++; }
            }
            used = true;
            check(t); long began = System.nanoTime();
            try { text = backend.decode(handle, samples, sampleRate); } finally { decode = System.nanoTime() - began; }
            check(t); if (text == null) text = "";
        } catch (Throwable failure) {
            stopped = t.cancelled.get() || failure instanceof CancellationException;
            if (!stopped || failure instanceof Error) { error = failure; poisoned = true; }
        } finally {
            if (deadline != null) deadline.cancel(false);
            try {
                // A cancelled cold load leaves a handle without published weights: release it, never leak it.
                if (used && handle != 0 && (poisoned || loaded == null)) unload(poisoned ? "native_error" : "cancelled_load");
                Memory info = memory.read(); after = info.available();
                if (!info.sufficient()) unload("memory_after");
            } catch (Throwable cleanup) {
                error = cleanup; poisoned = true;
                try { unload("cleanup_error"); } catch (Throwable ignored) { /* handle unpublished before release */ }
            }
            String eviction;
            synchronized (gate) { stopped |= t.cancelled.get() || t.version != version || closed; eviction = closed ? "session_closed" : evict; evict = ""; }
            try { if (!eviction.isEmpty()) unload(eviction); after = memory.read().available(); }
            catch (Throwable cleanup) { if (error == null) error = cleanup; }
            synchronized (gate) { if (active == t) active = null; pending--; finishedAt = System.nanoTime(); scheduleIdle(); }
            Metrics metrics = new Metrics(cold, error != null ? "failed" : stopped ? "stopped" : "completed", loads, attempts, unloads, lastUnload,
                ms(load), ms(decode), ms(started - t.submitted), ms(System.nanoTime() - t.submitted), audioMs,
                audioMs > 0 ? Math.round(ms(decode) / audioMs * 100.0) / 100.0 : 0, before, after);
            publish(metrics);
            if (error != null) t.result.completeExceptionally(error); else t.result.complete(new Output(text.trim(), stopped, metrics));
        }
    }
    /** Weights-only preparation: no decode, no audio; a silent way to warm the recognizer. */
    Ticket prepare(Model model) {
        synchronized (gate) {
            Ticket ticket = new Ticket(version);
            if (closed || pending >= 4) { ticket.result.completeExceptionally(new IOException(closed ? "Движок распознавания закрыт" : "Очередь распознавания занята")); return ticket; }
            if (!desired.equals(model.identity())) { desired = model.identity(); version++; if (active != null) abort(active); }
            ticket = new Ticket(version); Ticket admitted = ticket;
            cancelIdle(); pending++;
            worker.execute(() -> warm(admitted, model));
            return admitted;
        }
    }
    private void warm(Ticket t, Model model) {
        long started = System.nanoTime(), load = 0, before = -1, after = -1;
        boolean cold = false, used = false, stopped = false, poisoned = false;
        Throwable error = null;
        ScheduledFuture<?> deadline = null;
        try {
            check(t); synchronized (gate) { active = t; }
            deadline = timer.schedule(t::cancel, 60, TimeUnit.SECONDS); // A hung native load must not hold the queue forever.
            if (loaded != null && !loaded.identity().equals(model.identity())) unload("model_changed");
            Memory info = memory.read(); before = info.available();
            if (!info.sufficient()) { unload("memory_before"); throw new IOException("Сейчас мало свободной памяти для подготовки GigaAM."); }
            check(t); cold = loaded == null;
            if (cold) {
                used = true;
                long began = System.nanoTime(); attempts++;
                long created = backend.create(model.encoder(), model.decoder(), model.joiner(), model.tokens(), GigaAmModel.THREADS);
                if (created == 0) throw new IOException("Не удалось создать распознаватель GigaAM");
                synchronized (gate) { handle = created; }
                try { check(t); } finally { load = System.nanoTime() - began; }
                synchronized (gate) { loaded = model; loads++; }
            }
            used = true; check(t);
        } catch (Throwable failure) {
            stopped = t.cancelled.get() || failure instanceof CancellationException;
            if (!stopped || failure instanceof Error) { error = failure; poisoned = true; }
        } finally {
            if (deadline != null) deadline.cancel(false);
            try {
                if (used && handle != 0 && (poisoned || loaded == null)) unload(poisoned ? "native_error" : "cancelled_load");
                Memory info = memory.read(); after = info.available();
            } catch (Throwable cleanup) { error = cleanup; poisoned = true; }
            String eviction;
            synchronized (gate) { stopped |= t.cancelled.get() || t.version != version || closed; eviction = closed ? "session_closed" : evict; evict = ""; }
            try { if (!eviction.isEmpty()) unload(eviction); after = memory.read().available(); }
            catch (Throwable cleanup) { if (error == null) error = cleanup; }
            synchronized (gate) { if (active == t) active = null; pending--; finishedAt = System.nanoTime(); scheduleIdle(); }
            Metrics metrics = new Metrics(cold, error != null ? "failed" : stopped ? "stopped" : "prepared", loads, attempts, unloads, lastUnload,
                ms(load), 0, ms(started - t.submitted), ms(System.nanoTime() - t.submitted), 0, 0, before, after);
            publish(metrics);
            if (error != null) t.result.completeExceptionally(error); else t.result.complete(new Output("", stopped, metrics));
        }
    }
    private void publish(Metrics metrics) { latest = metrics; try { observer.accept(metrics); } catch (RuntimeException ignored) {} }
    private void cancelIdle() { idleVersion++; if (idle != null) { idle.cancel(false); idle = null; } }
    private void scheduleIdle() {
        if (closed || handle == 0 || active != null || pending > 0) return;
        cancelIdle(); long stamp = idleVersion;
        long remaining = Math.max(0, idleMillis - TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - finishedAt));
        idle = timer.schedule(() -> {
            synchronized (gate) { if (closed || stamp != idleVersion) return; worker.execute(() -> { synchronized (gate) { if (stamp != idleVersion || active != null || pending > 0) return; } unload("idle"); }); }
        }, remaining, TimeUnit.MILLISECONDS);
    }
    void idleTimeout(long millis) {
        if (millis < 1) throw new IllegalArgumentException();
        synchronized (gate) { if (closed) return; if (idleMillis == millis) return; idleMillis = millis; cancelIdle(); scheduleIdle(); }
    }
    void release(String reason, boolean cancelRequests) {
        synchronized (gate) {
            if (closed) return; cancelIdle(); evict = reason;
            if (cancelRequests) { version++; if (active != null) abort(active); }
            worker.execute(() -> { unload(reason); synchronized (gate) { if (evict.equals(reason)) evict = ""; } });
        }
    }
    /** Installer validation shares the same native owner and serial queue; never a second resident copy. */
    CompletableFuture<Void> probe(Model model, AtomicBoolean cancel) {
        CompletableFuture<Void> done = new CompletableFuture<>();
        synchronized (gate) {
            if (closed) { done.completeExceptionally(new IOException("Движок распознавания закрыт")); return done; }
            cancelIdle(); version++; if (active != null) abort(active);
            worker.execute(() -> {
                Ticket probe; synchronized (gate) { probe = new Ticket(version); active = probe; }
                ScheduledFuture<?> poll = timer.scheduleAtFixedRate(() -> { if (cancel.get()) probe.cancel(); }, 0, 25, TimeUnit.MILLISECONDS);
                try {
                    check(probe); if (cancel.get()) throw new CancellationException();
                    if (!memory.read().sufficient()) throw new IOException("Недостаточно памяти для проверки модели");
                    attempts++; long began = System.nanoTime();
                    long candidate = backend.create(model.encoder(), model.decoder(), model.joiner(), model.tokens(), GigaAmModel.THREADS);
                    if (candidate == 0) throw new IOException("Не удалось создать распознаватель для проверки модели");
                    synchronized (gate) { handle = candidate; }
                    double loadMs = ms(System.nanoTime() - began);
                    check(probe); synchronized (gate) { loaded = model; loads++; }
                    long decoded = System.nanoTime();
                    backend.decode(candidate, new float[GigaAmModel.SAMPLE_RATE / 2], GigaAmModel.SAMPLE_RATE); // 0.5 s of silence
                    check(probe); publish(new Metrics(true, "probe_ok", loads, attempts, unloads, "probe", loadMs, ms(System.nanoTime() - decoded), 0, ms(System.nanoTime() - began), 500, 0, -1, -1));
                } catch (Throwable failure) { done.completeExceptionally(failure); }
                finally { poll.cancel(false); try { unload("install_probe"); } finally { synchronized (gate) { if (active == probe) active = null; } } done.complete(null); }
            });
        }
        return done;
    }
    private void unload(String reason) {
        long old;
        synchronized (gate) { old = handle; handle = 0; loaded = null; }
        if (old == 0) return;
        backend.close(old); unloads++; lastUnload = reason;
        long available = -1; try { available = memory.read().available(); } catch (IOException ignored) {}
        publish(new Metrics(false, "unloaded", loads, attempts, unloads, reason, 0, 0, 0, 0, 0, 0, -1, available));
    }
    @Override public void close() {
        synchronized (gate) {
            if (closed) return; closed = true; version++; cancelIdle(); if (active != null) abort(active);
            worker.execute(() -> { try { unload("session_closed"); } finally { timer.shutdownNow(); worker.shutdown(); } });
        }
    }
}
