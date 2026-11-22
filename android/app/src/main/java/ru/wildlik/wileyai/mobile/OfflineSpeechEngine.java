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
        default void level(float value) {}
        default boolean wantsSpectrum() { return false; }
        default void spectrum(float[] bands) {}
        default void ready(Runnable startMicrophone) { startMicrophone.run(); }
        default void speechEnded(long elapsedRealtime) {}
        default void gigaStage(GigaAmSpeechEngine.Stage stage,long value) {}
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
            VoiceTelemetry.Capture capture = null;
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
                    capture=VoiceTelemetry.captureOpened(VoiceTelemetry.VOSK);DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());
                    post(ticket, () -> listener.state("Говорите сейчас"));
                    VoiceSpectrum spectrum = listener.wantsSpectrum() ? new VoiceSpectrum() : null; NeonWaveMath.LevelNormalizer visualLevel = new NeonWaveMath.LevelNormalizer();
                    short[] buffer = new short[2048]; long began = SystemClock.elapsedRealtime(), lastPartial = 0, lastLevel=0;
                    while (!cancelled && !finishing && SystemClock.elapsedRealtime() - began < Math.max(2000,Math.min(60000,timeoutMillis))) {
                        int n;
                        try { n = audio.read(buffer, 0, buffer.length); }
                        catch (IllegalStateException error) { if (finishing || cancelled) break; throw error; }
                        if (n <= 0) { if (finishing || cancelled) break; throw new IllegalStateException("Не удалось получить звук микрофона"); }
                        long now=SystemClock.elapsedRealtime();if(now-lastLevel>=150){lastLevel=now;double sum=0;for(int i=0;i<n;i++)sum+=(double)buffer[i]*buffer[i];float level=visualLevel.observe(Math.sqrt(sum/n));float[] bands=spectrum==null?null:spectrum.analyze(buffer,n);post(ticket,()->{listener.level(level);if(bands!=null)listener.spectrum(bands);});}
                        if (recognizer.acceptWaveForm(buffer, n)) {
                            String value = new JSONObject(recognizer.getResult()).optString("text").trim();
                            if (!value.isEmpty()) { text.append(value); break; }
                        } else if (SystemClock.elapsedRealtime() - lastPartial > 250) {
                            String partial = new JSONObject(recognizer.getPartialResult()).optString("partial"); lastPartial = SystemClock.elapsedRealtime();
                            if (!partial.isEmpty()) post(ticket, () -> listener.partial(partial));
                        }
                    }
                    if (!cancelled) {
                        long endpoint=SystemClock.elapsedRealtime();
                        post(ticket,()->listener.speechEnded(endpoint));
                        if(text.length()==0)text.append(new JSONObject(recognizer.getFinalResult()).optString("text"));
                    }
                }
                if (!cancelled) recognized[0] = text.toString().trim();
            } catch (SecurityException error) { post(ticket, () -> listener.error("Разрешите микрофон для локального распознавания")); }
            catch (OutOfMemoryError error) { post(ticket, () -> listener.error("Не хватило оперативной памяти. Речевая модель выгружена.")); }
            catch (LinkageError error) { post(ticket, () -> listener.error("Нативный движок Vosk несовместим с этим устройством")); }
            catch (Exception error) { post(ticket, () -> listener.error("Не удалось распознать речь. Проверьте микрофон и повторите установку комплекта, если ошибка сохраняется.")); }
            finally {
                AudioRecord recorder = audio; audio = null;
                if (recorder != null) { try { recorder.stop(); } catch (IllegalStateException ignored) {} recorder.release(); }
                if(capture!=null){capture.close();DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());}
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
