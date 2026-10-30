package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.ActivityManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;
import java.nio.file.Path;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** One bounded 15-second local microphone session, shared by chat and system assistant. */
final class OfflineSpeechEngine {
    interface Listener {
        default void ready(Runnable startMicrophone) { startMicrophone.run(); }
        void state(String message);
        void partial(String text);
        void result(String text);
        void error(String message);
        void finished();
    }
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean busy = new AtomicBoolean();
    private volatile boolean cancelled, finishing, closed;
    private volatile int session;
    private volatile AudioRecord audio;
    OfflineSpeechEngine(Context context) { this.context = context.getApplicationContext(); }
    boolean busy() { return busy.get(); }
    private void post(int ticket, Runnable callback) { main.post(() -> { if (!closed && !cancelled && ticket == session) callback.run(); }); }
    void start(Path path, Listener listener) {
        start(path,listener,15000);
    }
    void start(Path path, Listener listener,int timeoutMillis) {
        if (closed || !busy.compareAndSet(false, true)) return;
        cancelled = false; finishing = false; final int ticket = ++session;
        worker.execute(() -> {
            StringBuilder text = new StringBuilder();
            String[] recognized = {null};
            try {
                if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) throw new SecurityException();
                ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo(); ((ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(memory);
                if (memory.lowMemory || memory.availMem < 192L * 1024 * 1024) { post(ticket, () -> listener.error("Сейчас не хватает свободной памяти для распознавания. Закройте тяжёлые приложения и повторите.")); return; }
                post(ticket, () -> listener.state("Загружаю русский распознаватель…"));
                org.vosk.LibVosk.setLogLevel(org.vosk.LogLevel.WARNINGS);
                try (SpeechRuntime.Lease weights = SpeechRuntime.acquire(path); Recognizer recognizer = new Recognizer(weights.model(), 16000)) {
                    if (cancelled) return;
                    if (finishing) { recognized[0] = ""; return; }
                    // Announce readiness after decoder preparation and before capturing audio.
                    java.util.concurrent.CountDownLatch ready = new java.util.concurrent.CountDownLatch(1);
                    post(ticket, () -> listener.ready(ready::countDown));
                    long deadline = SystemClock.elapsedRealtime() + 10000;
                    while (!cancelled && !finishing && !ready.await(50, java.util.concurrent.TimeUnit.MILLISECONDS)) {
                        if (SystemClock.elapsedRealtime() >= deadline) throw new IllegalStateException("Сигнал готовности не завершён");
                    }
                    if (cancelled) return;
                    if (finishing) { recognized[0] = ""; return; }
                    int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    if (minimum <= 0) throw new IllegalStateException("Аудиоформат недоступен");
                    audio = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(minimum * 2, 8192));
                    if (audio.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("Микрофон недоступен");
                    audio.startRecording();
                    if (audio.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException("Микрофон занят");
                    post(ticket, () -> listener.state("Слушаю на телефоне · нажмите ■ для завершения"));
                    short[] buffer = new short[2048]; long began = SystemClock.elapsedRealtime(), lastPartial = 0;
                    while (!cancelled && !finishing && SystemClock.elapsedRealtime() - began < Math.max(2000,Math.min(60000,timeoutMillis))) {
                        int n;
                        try { n = audio.read(buffer, 0, buffer.length); }
                        catch (IllegalStateException error) { if (finishing || cancelled) break; throw error; }
                        if (n <= 0) { if (finishing || cancelled) break; throw new IllegalStateException("Не удалось получить звук микрофона"); }
                        if (recognizer.acceptWaveForm(buffer, n)) {
                            String value = new JSONObject(recognizer.getResult()).optString("text").trim();
                            if (!value.isEmpty()) { text.append(value); break; }
                        } else if (SystemClock.elapsedRealtime() - lastPartial > 250) {
                            String partial = new JSONObject(recognizer.getPartialResult()).optString("partial"); lastPartial = SystemClock.elapsedRealtime();
                            if (!partial.isEmpty()) post(ticket, () -> listener.partial(partial));
                        }
                    }
                    if (text.length() == 0 && !cancelled) text.append(new JSONObject(recognizer.getFinalResult()).optString("text"));
                }
                if (!cancelled) recognized[0] = text.toString().trim();
            } catch (SecurityException error) { post(ticket, () -> listener.error("Разрешите микрофон для локального распознавания")); }
            catch (OutOfMemoryError error) { post(ticket, () -> listener.error("Не хватило оперативной памяти. Речевая модель выгружена.")); }
            catch (LinkageError error) { post(ticket, () -> listener.error("Нативный движок Vosk несовместим с этим устройством")); }
            catch (Exception error) { post(ticket, () -> listener.error("Не удалось распознать речь. Проверьте микрофон и повторите установку комплекта, если ошибка сохраняется.")); }
            finally {
                AudioRecord recorder = audio; audio = null;
                if (recorder != null) { try { recorder.stop(); } catch (IllegalStateException ignored) {} recorder.release(); }
                busy.set(false);
                if (recognized[0] != null) { String result = recognized[0]; post(ticket, () -> listener.result(result)); }
                main.post(() -> { if (!closed && ticket == session) listener.finished(); });
            }
        });
    }
    void finish() { finishing = true; stopMicrophone(); }
    void cancel() { cancelled = true; stopMicrophone(); }
    private void stopMicrophone() { AudioRecord recorder = audio; if (recorder != null) { try { recorder.stop(); } catch (IllegalStateException ignored) {} } }
    void close() { closed = true; cancel(); worker.shutdown(); }
}
