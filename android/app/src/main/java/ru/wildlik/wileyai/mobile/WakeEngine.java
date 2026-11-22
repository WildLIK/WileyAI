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
import java.util.function.BiConsumer;

/** Local keyword decoder. Optional PCM handoff retains the same AudioRecord until the consumer closes it. */
final class WakeEngine {
    private final Context context; private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor(); private final AtomicBoolean busy = new AtomicBoolean();
    private volatile boolean cancelled, closed; private volatile int generation; private volatile AudioRecord recorder; private volatile PcmHandoff handoff; private final List<Runnable> paused = new ArrayList<>();
    WakeEngine(Context context) { this.context = context.getApplicationContext(); }
    boolean busy() { return busy.get(); }
    void start(Path path, String phrase, Runnable listening, Consumer<Boolean> detected, Consumer<String> error) {
        start(path, phrase, listening, false, (event, pcm) -> detected.accept(event.conversation()), error, () -> {});
    }
    void start(Path path, String phrase, Runnable listening, boolean continuous, BiConsumer<WakeActivation,PcmHandoff> detected, Consumer<String> error, Runnable idle) {
        start(path, phrase, listening, continuous, false, detected, error, idle);
    }
    void start(Path path, String phrase, Runnable listening, boolean continuous, boolean recoverPrefix, BiConsumer<WakeActivation,PcmHandoff> detected, Consumer<String> error, Runnable idle) {
        if (closed || !WakePhrase.valid(phrase) || !busy.compareAndSet(false, true)) return; cancelled = false; int ticket = ++generation;
        boolean prefixEnabled = recoverPrefix && continuous && WakePhrase.SHORT.equals(phrase);
        VoiceTelemetry.wakeStarted();DiagnosticLog.event(DiagnosticJournal.Event.WAKE_START,0);
        if (prefixEnabled) DiagnosticLog.event(DiagnosticJournal.Event.WAKE_PREFIX_ENABLED,1);
        worker.execute(() -> {
            boolean found = false, conversation = false, delivered = false; String failure = null;
            WakeActivation candidate = null;
            int stopReason=4,stage=0,heartbeatSamples=0,heartbeatFinals=0,heartbeatRejected=0;long framesRead=0;VoiceTelemetry.Capture capture=null;
            long captureId = SystemClock.elapsedRealtimeNanos();
            PcmHandoff pcm = continuous ? new PcmHandoff(16000 * 8, 16000 * 20) : null;
            handoff = pcm;
            try {
                if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) throw new SecurityException();
                stage=1;try (SpeechRuntime.Lease weights = SpeechRuntime.acquire(path)) {
                  String grammar = WakeVocabulary.grammar(weights.model(), phrase);
                  try (Recognizer decoder = new Recognizer(weights.model(), 16000, grammar)) {
                    decoder.setWords(true);
                    if (cancelled) return;
                    stage=2;int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    if (minimum <= 0) throw new IllegalStateException();
                    recorder = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(8192, minimum * 2));
                    if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException();
                    recorder.startRecording(); if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException();
                    capture=VoiceTelemetry.captureOpened(VoiceTelemetry.WAKE);stage=3;DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());DiagnosticLog.event(DiagnosticJournal.Event.WAKE_READY,0);
                    main.post(() -> { if (!closed && !cancelled && generation == ticket) listening.run(); }); short[] buffer = new short[2048];
                    while (!cancelled) {
                        int n; try { n = recorder.read(buffer, 0, buffer.length); } catch (IllegalStateException stopped) { if (cancelled) break; throw stopped; }
                        if (n <= 0) { if (cancelled) break; throw new IllegalStateException(); }
                        framesRead+=n; heartbeatSamples+=n;
                        if (heartbeatSamples >= 80000) {
                            DiagnosticLog.event(DiagnosticJournal.Event.WAKE_READ_SAMPLES,heartbeatSamples);
                            DiagnosticLog.event(DiagnosticJournal.Event.WAKE_DECODER_FINALS,heartbeatFinals);
                            DiagnosticLog.event(DiagnosticJournal.Event.WAKE_REJECTED_FINALS,heartbeatRejected);
                            heartbeatSamples=heartbeatFinals=heartbeatRejected=0;
                        }
                        if (pcm != null) pcm.append(buffer,n);
                        H2Shadow.feed(captureId,framesRead-n,buffer,n);
                        AcousticDiagnostics acoustic = AcousticDiagnostics.current();
                        boolean observe = acoustic != null && acoustic.capturingInput();
                        if (observe) acousticFeed(acoustic, captureId, framesRead - n, buffer, n, grammar, phrase);
                        long began = observe ? SystemClock.elapsedRealtimeNanos() : 0;
                        if (!decoder.acceptWaveForm(buffer, n)) {
                            if (observe) acoustic.partial(decoder, captureId);
                            continue;
                        }
                        heartbeatFinals++;
                        JSONObject result = new JSONObject(decoder.getResult()); JSONArray words = result.optJSONArray("result"); double confidence = 1;
                        if (words == null || words.length() < 1) {
                            heartbeatRejected++;
                            if (observe) acousticCandidate(acoustic, captureId, null, grammar, phrase, result,
                                    "no_words", Double.NaN, framesRead, began);
                            continue;
                        }
                        for (int i = 0; i < words.length(); i++) confidence = Math.min(confidence, words.getJSONObject(i).optDouble("conf", 0));
                        String text = result.optString("text");
                        conversation=WakePhrase.conversation(phrase,text,confidence);
                        boolean exact = conversation || WakePhrase.matches(phrase,text,confidence);
                        WakeFinalPrefix.Match recovery = null;
                        long recoveryStarted = !exact && prefixEnabled ? SystemClock.elapsedRealtimeNanos() : 0;
                        if (!exact && prefixEnabled) recovery = recover(words,framesRead);
                        if (exact || recovery != null) {
                            double wordEnd=words.getJSONObject(words.length()-1).optDouble("end",Double.NaN);long wordSample=Double.isFinite(wordEnd)?Math.round(wordEnd*16000):-1;
                            if (recovery != null) {
                                wordSample = recovery.end();
                                confidence = recovery.confidence();
                            }
                            long lag=wordSample>=0&&wordSample<=framesRead?(framesRead-wordSample)*1000/16000:-1;
                            WakeActivation event=new WakeActivation(ThreadLocalRandom.current().nextLong(1,Long.MAX_VALUE),
                                SystemClock.elapsedRealtime(),WakePhrase.variant(recovery==null?text:recovery.phrase(),conversation),conversation,
                                (int)Math.round(confidence*1000),lag);
                            if (recovery != null) DiagnosticLog.event(DiagnosticJournal.Event.WAKE_PREFIX_RECOVERY_US,
                                (SystemClock.elapsedRealtimeNanos()-recoveryStarted)/1000);
                            if (observe && acousticCandidate(acoustic, captureId, event, grammar, phrase, result,
                                    recovery!=null?"final_prefix":conversation?"exact_conversation":"exact_wake", confidence, framesRead, began)) continue;
                            H2Shadow.voskAccepted();
                            H2Shadow.end(captureId);
                            found = true;
                            candidate=event;
                            if(wordSample>=0&&wordSample<=framesRead){DiagnosticLog.event(DiagnosticJournal.Event.WAKE_DETECTION_SAMPLE,framesRead);DiagnosticLog.event(DiagnosticJournal.Event.WAKE_DETECTION_LAG_MS,(framesRead-wordSample)*1000/16000);}
                            if (pcm != null && !conversation) {
                                long boundary = recovery==null?wordSample:recovery.commandStart();
                                try {
                                    if (boundary < 0 || boundary > pcm.position()) throw new IllegalArgumentException();
                                    pcm.activate(boundary);
                                    DiagnosticLog.event(DiagnosticJournal.Event.PCM_BOUNDARY_SAMPLE,boundary);DiagnosticLog.event(DiagnosticJournal.Event.PCM_BUFFERED_SAMPLES,pcm.bufferedSamples());
                                    android.util.Log.i("WileyWake","handoff_ready retained_samples="+(pcm.position()-boundary));
                                    main.post(() -> { if (!closed && !cancelled && generation == ticket) detected.accept(event,pcm); else pcm.close(); });
                                    delivered = true;
                                    while (!cancelled && pcm.isActive()) {
                                        int more; try { more = recorder.read(buffer,0,buffer.length); } catch (IllegalStateException stopped) { if (cancelled || !pcm.isActive()) break; throw stopped; }
                                        if (more <= 0) { if (cancelled || !pcm.isActive()) break; throw new IllegalStateException(); }
                                        try { pcm.append(buffer,more); } catch (IllegalStateException stopped) { if (!pcm.isActive()) break; throw stopped; }
                                        AcousticDiagnostics tail = AcousticDiagnostics.current();
                                        if (tail != null && tail.capturingInput()) acousticFeed(tail, captureId, framesRead, buffer, more, grammar, phrase);
                                        framesRead += more;
                                    }
                                } catch (IllegalArgumentException unavailable) { pcm.close(); }
                            }
                            break;
                        }
                        heartbeatRejected++;
                        if (observe) acousticCandidate(acoustic, captureId, null, grammar, phrase, result,
                                !Double.isFinite(confidence) || confidence < WakePhrase.MIN_CONFIDENCE || confidence > 1
                                        ? "confidence_outside_threshold" : "phrase_not_allowed", confidence, framesRead, began);
                    }
                  }
                }
            } catch (SecurityException denied) { stopReason=3;failure = "Разрешите микрофон для голосовой активации"; }
            catch (Exception | LinkageError problem) { if (!cancelled) {stopReason=stage==1?6:stage>=2?7:4;failure = "Не удалось слушать фразу. Проверьте микрофон и русский комплект Vosk.";} }
            catch (OutOfMemoryError problem) { stopReason=5;failure = "Недостаточно памяти для голосовой активации"; }
            finally {
                H2Shadow.end(captureId);
                int finalReason = cancelled ? 1 : found ? 2 : stopReason;
                AcousticDiagnostics acoustic = AcousticDiagnostics.current();
                if (acoustic != null && acoustic.capturingInput()) {
                    try { acoustic.captureEnd(captureId, finalReason); } catch (RuntimeException ignored) {}
                }
                if (pcm != null) { if (delivered && failure == null && !cancelled) pcm.seal(); else pcm.close(); }
                if (handoff == pcm) handoff = null;
                AudioRecord audio = recorder; recorder = null; if (audio != null) { try { audio.stop(); } catch (IllegalStateException ignored) {} audio.release(); }
                if(capture!=null){capture.close();DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());}VoiceTelemetry.wakeStopped();DiagnosticLog.event(DiagnosticJournal.Event.WAKE_STOP_REASON,cancelled?1:found?2:stopReason);
                if(delivered)android.util.Log.i("WileyWake","handoff_capture_closed");
                WakeActivation event = candidate; boolean sent=delivered; String message = failure;
                main.post(() -> {
                    boolean stopped = cancelled; busy.set(false);
                    List<Runnable> callbacks = new ArrayList<>(paused); paused.clear(); for (Runnable callback : callbacks) callback.run();
                    if (!closed && !stopped && generation == ticket) { if (message != null && !sent) error.accept(message); else if (event!=null && !sent) detected.accept(event,null); }
                    idle.run();
                });
            }
        });
    }
    static WakeFinalPrefix.Match recover(JSONArray words,long captured) {
        try {
            if (words.length()<2 || words.length()>5) return null;
            List<WakeFinalPrefix.Word> candidates = new ArrayList<>(words.length());
            for (int i=0;i<words.length();i++) {
                JSONObject word = words.getJSONObject(i);
                candidates.add(new WakeFinalPrefix.Word(word.optString("word"),word.optDouble("start",Double.NaN),
                    word.optDouble("end",Double.NaN),word.optDouble("conf",Double.NaN)));
            }
            return WakeFinalPrefix.recover(candidates,captured);
        } catch (Exception malformed) {
            return null;
        }
    }
    private void acousticFeed(AcousticDiagnostics acoustic, long capture, long start, short[] samples, int count, String grammar, String preset) {
        try { acoustic.feed(recorder, capture, start, samples, count, grammar, preset); }
        catch (RuntimeException ignored) { acoustic.stop("diagnostic_error"); }
    }
    private static boolean acousticCandidate(AcousticDiagnostics acoustic, long capture, WakeActivation event, String grammar,
                                              String phrase, JSONObject finalResult, String reason, double confidence, long frames, long started) {
        try { return acoustic.candidate(capture, event, grammar, phrase, finalResult, reason,
                confidence, frames, (SystemClock.elapsedRealtimeNanos() - started) / 1000); }
        catch (RuntimeException ignored) { return event != null && acoustic.suppresses(); }
    }
    void pause(Runnable after) { cancelled = true; PcmHandoff pcm=handoff; if(pcm!=null)pcm.close(); if (!busy.get()) { after.run(); return; } paused.add(after); AudioRecord audio = recorder; if (audio != null) try { audio.stop(); } catch (IllegalStateException ignored) {} }
    void close() { closed = true; pause(() -> {}); worker.shutdown(); }
}
