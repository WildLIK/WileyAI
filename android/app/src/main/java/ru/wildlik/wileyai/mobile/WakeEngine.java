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

/** Local keyword decoder (Vosk fallback + LiveKit C v2 + optional CAM++ speaker filter). */
final class WakeEngine {
    private static final int BLOCK = WakeComparisonPcm.BLOCK; // 1280 samples (80 ms)
    private static final int COOLDOWN_BLOCKS = 10;            // 800 ms
    private static final int PRE_ROLL_SAMPLES = WakeActivationJournal.PRE_SAMPLES;   // 24000 (1.5 s)
    private static final int POST_ROLL_SAMPLES = WakeActivationJournal.POST_SAMPLES; // 24000 (1.5 s)

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
        int selectedEngine = WakeSettings.wakeEngine(context);
        boolean useLiveKit = WakeModelAssets.liveKitEligible(context, selectedEngine, phrase);
        VoiceTelemetry.wakeStarted();DiagnosticLog.event(DiagnosticJournal.Event.WAKE_START,0);
        if (prefixEnabled) DiagnosticLog.event(DiagnosticJournal.Event.WAKE_PREFIX_ENABLED,1);
        worker.execute(() -> {
            if (useLiveKit) {
                runLiveKit(ticket, phrase, listening, continuous, selectedEngine, detected, error, idle);
            } else {
                runVosk(ticket, path, phrase, listening, continuous, prefixEnabled, detected, error, idle);
            }
        });
    }

    private void runLiveKit(int ticket, String phrase, Runnable listening, boolean continuous, int selectedEngine,
                            BiConsumer<WakeActivation, PcmHandoff> detected, Consumer<String> error, Runnable idle) {
        boolean found = false, delivered = false;
        String failure = null;
        WakeActivation candidate = null;
        int stopReason = 4, stage = 0, heartbeatSamples = 0;
        long framesRead = 0;
        VoiceTelemetry.Capture capture = null;
        AudioRouteManager.EffectsSession effects = null;
        PcmHandoff pcm = continuous ? new PcmHandoff(16000 * 8, 16000 * 20) : null;
        handoff = pcm;
        long lkHandle = 0;
        OwnerSpeakerFilter speakerFilter = null;
        try {
            if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) throw new SecurityException();
            stage = 1;
            System.loadLibrary("wiley_livekit_compare");
            Path modelFile = WakeModelAssets.ensureLiveKitV2(context);
            lkHandle = WakeComparison.open(modelFile.toAbsolutePath().toString());
            if (lkHandle == 0) throw new IllegalStateException("LiveKit C v2 open failed");

            if (selectedEngine == WakeSettings.ENGINE_LIVEKIT_V2_CAM) {
                speakerFilter = OwnerSpeakerFilter.open(WakeModelAssets.ensureCamPlus(context), 1);
            }
            if (cancelled) return;

            stage = 2;
            int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException();
            recorder = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(8192, minimum * 2));
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException();
            effects = AudioRouteManager.attachEffects(context, recorder, false);
            recorder.startRecording();
            if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException();
            capture = VoiceTelemetry.captureOpened(VoiceTelemetry.WAKE);
            stage = 3;
            DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT, VoiceTelemetry.snapshot().captureCount());
            DiagnosticLog.event(DiagnosticJournal.Event.WAKE_READY, 0);
            main.post(() -> { if (!closed && !cancelled && generation == ticket) listening.run(); });

            short[] buffer = new short[2048];
            short[] block = new short[BLOCK];
            int blockPos = 0;
            PcmRingBuffer preRoll = new PcmRingBuffer(PRE_ROLL_SAMPLES);
            float lkThreshold = WakeSettings.liveKitThreshold(context);
            float camThreshold = OwnerSpeakerFilter.threshold(context);
            String engineName = speakerFilter != null ? "livekit_c_v2_cam" : "livekit_c_v2";
            boolean armed = true;
            int cooldown = 0;
            String micRoute = AudioRouteManager.describeMicRoute(recorder);
            String acceptedJournalId = null;

            while (!cancelled) {
                int n;
                try { n = recorder.read(buffer, 0, buffer.length); }
                catch (IllegalStateException stopped) { if (cancelled) break; throw stopped; }
                if (n <= 0) { if (cancelled) break; throw new IllegalStateException(); }
                framesRead += n;
                heartbeatSamples += n;
                if (heartbeatSamples >= 80000) {
                    DiagnosticLog.event(DiagnosticJournal.Event.WAKE_READ_SAMPLES, heartbeatSamples);
                    heartbeatSamples = 0;
                }
                if (pcm != null) pcm.append(buffer, n);
                preRoll.append(buffer, 0, n);

                int off = 0;
                while (off < n && !cancelled) {
                    int take = Math.min(n - off, BLOCK - blockPos);
                    System.arraycopy(buffer, off, block, blockPos, take);
                    off += take;
                    blockPos += take;
                    if (blockPos == BLOCK) {
                        blockPos = 0;
                        if (cooldown > 0) cooldown--;
                        long t0 = SystemClock.elapsedRealtimeNanos();
                        float score = WakeComparison.score(lkHandle, block);
                        long lkUs = (SystemClock.elapsedRealtimeNanos() - t0) / 1000L;
                        if (!Float.isFinite(score)) throw new IllegalStateException("Non-finite LiveKit score");

                        if (score >= lkThreshold) {
                            if (armed && cooldown == 0) {
                                armed = false;
                                cooldown = COOLDOWN_BLOCKS;
                                boolean ttsSpeaking = HandsFreeService.acousticSpeaking();
                                short[] preSnapshot = preRoll.snapshot();
                                double camSim = Double.NaN;
                                long camMs = -1;
                                boolean speakerOk = true;
                                if (speakerFilter != null) {
                                    OwnerSpeakerFilter.Result res = speakerFilter.verify(context, preSnapshot, preSnapshot.length);
                                    camSim = res.similarity();
                                    camMs = res.elapsedUs() / 1000L;
                                    speakerOk = res.accepted();
                                }
                                long wakeLatencyMs = lkUs / 1000L;
                                if (!speakerOk) {
                                    WakeActivationJournal.recordEventAsync(
                                            context, engineName, score, camSim, camThreshold, lkThreshold,
                                            micRoute, ttsSpeaking, wakeLatencyMs, camMs,
                                            "rejected_cam", "cam_speaker_rejected", preSnapshot);
                                    continue;
                                }
                                acceptedJournalId = WakeActivationJournal.recordEventAsync(
                                        context, engineName, score, camSim, camThreshold, lkThreshold,
                                        micRoute, ttsSpeaking, wakeLatencyMs, camMs,
                                        "accepted", "accepted", preSnapshot);

                                int variant = WakePhrase.SHORT.equals(phrase) ? 1 : 6;
                                candidate = new WakeActivation(
                                        ThreadLocalRandom.current().nextLong(1, Long.MAX_VALUE),
                                        SystemClock.elapsedRealtime(), variant, false,
                                        (int) Math.round(score * 1000.0), wakeLatencyMs, acceptedJournalId);
                                found = true;
                                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_DETECTION_SAMPLE, framesRead);
                                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_DETECTION_LAG_MS, wakeLatencyMs);

                                if (pcm != null) {
                                    long boundary = Math.max(0, framesRead - 1280L * 8L); // 640 ms pre-roll for fused commands
                                    try {
                                        pcm.activate(boundary);
                                        DiagnosticLog.event(DiagnosticJournal.Event.PCM_BOUNDARY_SAMPLE, boundary);
                                        DiagnosticLog.event(DiagnosticJournal.Event.PCM_BUFFERED_SAMPLES, pcm.bufferedSamples());
                                        WakeActivation event = candidate;
                                        main.post(() -> { if (!closed && !cancelled && generation == ticket) detected.accept(event, pcm); else pcm.close(); });
                                        delivered = true;
                                        short[] postBuf = new short[POST_ROLL_SAMPLES];
                                        int postLen = 0;
                                        while (!cancelled && pcm.isActive()) {
                                            int more;
                                            try { more = recorder.read(buffer, 0, buffer.length); }
                                            catch (IllegalStateException stopped) { if (cancelled || !pcm.isActive()) break; throw stopped; }
                                            if (more <= 0) { if (cancelled || !pcm.isActive()) break; throw new IllegalStateException(); }
                                            if (postLen < postBuf.length) {
                                                int copyN = Math.min(more, postBuf.length - postLen);
                                                System.arraycopy(buffer, 0, postBuf, postLen, copyN);
                                                postLen += copyN;
                                                if (postLen == postBuf.length && acceptedJournalId != null) {
                                                    WakeActivationJournal.savePostAudioAsync(context, acceptedJournalId, postBuf, postLen);
                                                    acceptedJournalId = null;
                                                }
                                            }
                                            try { pcm.append(buffer, more); }
                                            catch (IllegalStateException stopped) { if (!pcm.isActive()) break; throw stopped; }
                                            framesRead += more;
                                        }
                                        if (postLen > 0 && acceptedJournalId != null) {
                                            WakeActivationJournal.savePostAudioAsync(context, acceptedJournalId, postBuf, postLen);
                                        }
                                    } catch (IllegalArgumentException unavailable) {
                                        pcm.close();
                                    }
                                }
                                break;
                            }
                        } else {
                            armed = true;
                        }
                    }
                }
                if (found) break;
            }
        } catch (SecurityException denied) {
            stopReason = 3;
            failure = "Разрешите микрофон для голосовой активации";
        } catch (Exception | LinkageError problem) {
            if (!cancelled) {
                stopReason = stage == 1 ? 6 : stage >= 2 ? 7 : 4;
                failure = "Не удалось запустить LiveKit C v2. Переключитесь на резервный Vosk в настройках.";
            }
        } catch (OutOfMemoryError problem) {
            stopReason = 5;
            failure = "Недостаточно памяти для голосовой активации";
        } finally {
            if (lkHandle != 0) WakeComparison.close(lkHandle);
            if (speakerFilter != null) speakerFilter.close();
            if (effects != null) effects.close();
            if (pcm != null) { if (delivered && failure == null && !cancelled) pcm.seal(); else pcm.close(); }
            if (handoff == pcm) handoff = null;
            AudioRecord audio = recorder; recorder = null;
            if (audio != null) { try { audio.stop(); } catch (IllegalStateException ignored) {} audio.release(); }
            if (capture != null) { capture.close(); DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT, VoiceTelemetry.snapshot().captureCount()); }
            VoiceTelemetry.wakeStopped();
            DiagnosticLog.event(DiagnosticJournal.Event.WAKE_STOP_REASON, cancelled ? 1 : found ? 2 : stopReason);
            WakeActivation event = candidate; boolean sent = delivered; String message = failure;
            main.post(() -> {
                boolean stopped = cancelled; busy.set(false);
                List<Runnable> callbacks = new ArrayList<>(paused); paused.clear(); for (Runnable callback : callbacks) callback.run();
                if (!closed && !stopped && generation == ticket) {
                    if (message != null && !sent) error.accept(message);
                    else if (event != null && !sent) detected.accept(event, null);
                }
                idle.run();
            });
        }
    }

    private void runVosk(int ticket, Path path, String phrase, Runnable listening, boolean continuous, boolean prefixEnabled,
                         BiConsumer<WakeActivation,PcmHandoff> detected, Consumer<String> error, Runnable idle) {
        boolean found = false, conversation = false, delivered = false; String failure = null;
        WakeActivation candidate = null;
        int stopReason=4,stage=0,heartbeatSamples=0,heartbeatFinals=0,heartbeatRejected=0;long framesRead=0;VoiceTelemetry.Capture capture=null;
        long captureId = SystemClock.elapsedRealtimeNanos();
        PcmHandoff pcm = continuous ? new PcmHandoff(16000 * 8, 16000 * 20) : null;
        handoff = pcm;
        AudioRouteManager.EffectsSession effects = null;
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
                effects = AudioRouteManager.attachEffects(context, recorder, false);
                recorder.startRecording(); if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException();
                capture=VoiceTelemetry.captureOpened(VoiceTelemetry.WAKE);stage=3;DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());DiagnosticLog.event(DiagnosticJournal.Event.WAKE_READY,0);
                main.post(() -> { if (!closed && !cancelled && generation == ticket) listening.run(); }); short[] buffer = new short[2048];
                PcmRingBuffer preRoll = new PcmRingBuffer(PRE_ROLL_SAMPLES);
                String micRoute = AudioRouteManager.describeMicRoute(recorder);
                WakeComparison previousComparison = null;
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
                    WakeComparison comparison = WakeComparison.forBlock(phrase);
                    if (comparison != previousComparison) {
                        decoder.reset();
                        previousComparison = comparison;
                    }
                    if (comparison != null) {
                        long tick = SystemClock.elapsedRealtimeNanos(), cpu = Debug.threadCpuTimeNanos();
                        WakeComparison.VoskFinal finalEvent = decoder.acceptWaveForm(buffer, n)
                                ? compareFinal(new JSONObject(decoder.getResult()), phrase, framesRead) : null;
                        comparison.offer(recorder, captureId, framesRead - n, buffer, n, finalEvent,
                                (SystemClock.elapsedRealtimeNanos() - tick) / 1000,
                                (Debug.threadCpuTimeNanos() - cpu) / 1000, grammar);
                        continue;
                    }
                    if (pcm != null) pcm.append(buffer,n);
                    preRoll.append(buffer, 0, n);
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
                        String journalId = WakeActivationJournal.recordEventAsync(
                                context, "vosk", confidence, Double.NaN, Double.NaN, Double.NaN,
                                micRoute, HandsFreeService.acousticSpeaking(), lag, -1L,
                                "accepted", recovery != null ? "final_prefix" : conversation ? "exact_conversation" : "exact_wake",
                                preRoll.snapshot());
                        WakeActivation event=new WakeActivation(ThreadLocalRandom.current().nextLong(1,Long.MAX_VALUE),
                            SystemClock.elapsedRealtime(),WakePhrase.variant(recovery==null?text:recovery.phrase(),conversation),conversation,
                            (int)Math.round(confidence*1000),lag,journalId);
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
                                short[] postBuf = new short[POST_ROLL_SAMPLES];
                                int postLen = 0;
                                while (!cancelled && pcm.isActive()) {
                                    int more; try { more = recorder.read(buffer,0,buffer.length); } catch (IllegalStateException stopped) { if (cancelled || !pcm.isActive()) break; throw stopped; }
                                    if (more <= 0) { if (cancelled || !pcm.isActive()) break; throw new IllegalStateException(); }
                                    if (postLen < postBuf.length) {
                                        int copyN = Math.min(more, postBuf.length - postLen);
                                        System.arraycopy(buffer, 0, postBuf, postLen, copyN);
                                        postLen += copyN;
                                        if (postLen == postBuf.length && journalId != null) {
                                            WakeActivationJournal.savePostAudioAsync(context, journalId, postBuf, postLen);
                                            journalId = null;
                                        }
                                    }
                                    try { pcm.append(buffer,more); } catch (IllegalStateException stopped) { if (!pcm.isActive()) break; throw stopped; }
                                    AcousticDiagnostics tail = AcousticDiagnostics.current();
                                    if (tail != null && tail.capturingInput()) acousticFeed(tail, captureId, framesRead, buffer, more, grammar, phrase);
                                    framesRead += more;
                                }
                                if (postLen > 0 && journalId != null) {
                                    WakeActivationJournal.savePostAudioAsync(context, journalId, postBuf, postLen);
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
            if (effects != null) effects.close();
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
    }

    private static WakeComparison.VoskFinal compareFinal(JSONObject result, String phrase, long frames)
            throws JSONException {
        JSONArray words = result.optJSONArray("result");
        if (words == null || words.length() == 0)
            return new WakeComparison.VoskFinal(false, false, Double.NaN, Double.NaN, "no_words");
        double confidence = 1;
        for (int i = 0; i < words.length(); i++) confidence = Math.min(confidence, words.getJSONObject(i).optDouble("conf", 0));
        String text = result.optString("text");
        boolean conversation = WakePhrase.conversation(phrase, text, confidence);
        boolean exact = conversation || WakePhrase.matches(phrase, text, confidence);
        WakeFinalPrefix.Match prefix = exact ? null : recover(words, frames);
        String reason = exact ? (conversation ? "exact_conversation" : "exact_wake")
                : prefix != null ? "final_prefix"
                : !Double.isFinite(confidence) || confidence < WakePhrase.MIN_CONFIDENCE || confidence > 1
                        ? "confidence_outside_threshold" : "phrase_not_allowed";
        return new WakeComparison.VoskFinal(exact, prefix != null, confidence,
                prefix == null ? Double.NaN : prefix.confidence(), reason);
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
