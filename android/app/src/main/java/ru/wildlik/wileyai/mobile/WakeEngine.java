package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.content.*;
import android.content.pm.PackageManager;
import android.media.*;
import android.os.*;
import org.json.*;
import org.vosk.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** Local keyword-only decoder. Audio is neither saved nor sent anywhere. Releases microphone before callbacks. */
final class WakeEngine {
    private final Context context; private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor(); private final AtomicBoolean busy = new AtomicBoolean();
    private volatile boolean cancelled, closed; private volatile int generation; private volatile AudioRecord recorder; private final List<Runnable> paused = new ArrayList<>();
    WakeEngine(Context context) { this.context = context.getApplicationContext(); }
    boolean busy() { return busy.get(); }
    void start(Path path, String phrase, Runnable listening, Consumer<Boolean> detected, Consumer<String> error) {
        if (closed || !WakePhrase.valid(phrase) || !busy.compareAndSet(false, true)) return; cancelled = false; int ticket = ++generation;
        worker.execute(() -> {
            boolean found = false, conversation = false; String failure = null;
            try {
                if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) throw new SecurityException();
                try (SpeechRuntime.Lease weights = SpeechRuntime.acquire(path); Recognizer decoder = new Recognizer(weights.model(), 16000, WakeVocabulary.grammar(weights.model(), phrase))) {
                    decoder.setWords(true);
                    if (cancelled) return;
                    int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    if (minimum <= 0) throw new IllegalStateException();
                    recorder = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(8192, minimum * 2));
                    if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException();
                    recorder.startRecording(); if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException();
                    main.post(() -> { if (!closed && !cancelled && generation == ticket) listening.run(); }); short[] buffer = new short[2048];
                    while (!cancelled) {
                        int n; try { n = recorder.read(buffer, 0, buffer.length); } catch (IllegalStateException stopped) { if (cancelled) break; throw stopped; }
                        if (n <= 0) { if (cancelled) break; throw new IllegalStateException(); }
                        if (!decoder.acceptWaveForm(buffer, n)) continue;
                        JSONObject result = new JSONObject(decoder.getResult()); JSONArray words = result.optJSONArray("result"); double confidence = 1;
                        if (words == null || words.length() < 2) continue;
                        for (int i = 0; i < words.length(); i++) confidence = Math.min(confidence, words.getJSONObject(i).optDouble("conf", 0));
                        conversation=WakePhrase.conversation(phrase,result.optString("text"),confidence);
                        if (conversation || WakePhrase.matches(phrase, result.optString("text"), confidence)) { found = true; break; }
                    }
                }
            } catch (SecurityException denied) { failure = "Разрешите микрофон для голосовой активации"; }
            catch (Exception | LinkageError problem) { if (!cancelled) failure = "Не удалось слушать фразу. Проверьте микрофон и русский комплект Vosk."; }
            catch (OutOfMemoryError problem) { failure = "Недостаточно памяти для голосовой активации"; }
            finally {
                AudioRecord audio = recorder; recorder = null; if (audio != null) { try { audio.stop(); } catch (IllegalStateException ignored) {} audio.release(); }
                boolean wake = found, dialogue=conversation; String message = failure;
                main.post(() -> {
                    boolean stopped = cancelled; busy.set(false);
                    List<Runnable> callbacks = new ArrayList<>(paused); paused.clear(); for (Runnable callback : callbacks) callback.run();
                    if (closed || stopped || generation != ticket) return; if (message != null) error.accept(message); else if (wake) detected.accept(dialogue);
                });
            }
        });
    }
    void pause(Runnable after) { cancelled = true; if (!busy.get()) { after.run(); return; } paused.add(after); AudioRecord audio = recorder; if (audio != null) try { audio.stop(); } catch (IllegalStateException ignored) {} }
    void close() { closed = true; pause(() -> {}); worker.shutdown(); }
}
