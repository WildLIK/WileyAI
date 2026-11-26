package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Same microphone protocol as OfflineSpeechEngine (one bounded session, ready latch, finish/cancel),
 * with a speech detector in place of the Vosk decoder silence rule. Capture starts before the
 * GigaAM weights finish loading, and the decode is queued behind preparation.
 */
final class GigaAmSpeechEngine {
    enum Stage { ENDPOINT, PCM_DRAINED, SUBMITTED, QUEUE_DURATION, DECODE_DURATION, TEXT_READY }
    private static final int CHUNK = 2048; // 128 ms at 16 kHz
    private static final long MAX_BUFFER_MS = 15000, ENDPOINT_SILENCE_MS = 800, MIN_SPEECH_MS = 200, DECODE_WAIT_MS = 12000;
    private final Context context;
    private final GigaAmRuntime runtime;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean busy = new AtomicBoolean();
    private volatile boolean cancelled, finishing, closed;
    private volatile int session;
    private volatile AudioRecord audio;
    private volatile PcmHandoff externalAudio;
    private volatile GigaAmSession.Ticket decodeJob;
    GigaAmSpeechEngine(Context context, GigaAmRuntime runtime) { this.context = context.getApplicationContext(); this.runtime = runtime; }
    boolean busy() { return busy.get(); }
    private void post(int ticket, Runnable callback) { main.post(() -> { if (!closed && !cancelled && ticket == session) callback.run(); }); }
    void start(int timeoutMillis, OfflineSpeechEngine.Listener listener) {
        if (closed || !busy.compareAndSet(false, true)) return;
        cancelled = false; finishing = false; final int ticket = ++session;
        worker.execute(() -> run(ticket, listener, Math.max(2000, Math.min(60000, timeoutMillis)), null));
    }
    /** Accepts an already activated, continuously fed PCM source; caller owns the capture. */
    void startFromPcm(int timeoutMillis, OfflineSpeechEngine.Listener listener, PcmHandoff source) {
        if (source == null || !source.isActive()) throw new IllegalArgumentException("PCM source must be active");
        if (closed || !busy.compareAndSet(false, true)) { source.close(); return; }
        cancelled = false; finishing = false; final int ticket = ++session;
        externalAudio = source;
        worker.execute(() -> run(ticket, listener, Math.max(2000, Math.min(60000, timeoutMillis)), source));
    }
    private void run(int ticket, OfflineSpeechEngine.Listener listener, int timeoutMillis, PcmHandoff source) {
        List<short[]> kept = new ArrayList<>();
        String[] recognized = {null};
        AudioRecord recorder = null;
        AudioRouteManager.EffectsSession effects = null;
        VoiceTelemetry.Capture capture = null;
        GigaAmSileroVad silero = null;
        PcmRingBuffer sileroPreRoll = null;
        EnergyVad vad = new EnergyVad(source != null ? 120 : 300);
        long startedAt=SystemClock.elapsedRealtime(),frames=0,sampleCount=0;
        String reason="unknown", vadBackend="energy";
        android.util.Log.i("WileyVoice","session_started id="+ticket+" engine=gigaam source="+(source==null?"microphone":"handoff"));
        try {
            if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) throw new SecurityException();
            if (GigaAmModelManager.activeModel(context) == null) throw new IllegalStateException("Модель GigaAM v3 не установлена. Установите её в «Компоненты → Голос → Распознавание».");
            runtime.prepare(); // Weights warm up while the user is invited to speak.
            if (source != null && !cancelled && context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE)
                    .getBoolean(GigaAmSileroVad.ENABLED, true)) {
                long started = SystemClock.elapsedRealtime();
                try {
                    silero = GigaAmSileroVad.open(context.getAssets());
                    sileroPreRoll = new PcmRingBuffer(2 * CHUNK);
                    vadBackend = "silero";
                    android.util.Log.i("WileyVoice", "vad_ready id=" + ticket + " backend=silero elapsed_ms=" + (SystemClock.elapsedRealtime()-started));
                } catch (ReflectiveOperationException | IOException | RuntimeException | LinkageError unavailable) {
                    android.util.Log.i("WileyVoice", "vad_fallback id=" + ticket + " reason=initialization");
                }
            }
            if (source == null) {
            int minimum = AudioRecord.getMinBufferSize(GigaAmModel.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException("Аудиоформат недоступен");
            recorder = new AudioRecord(AudioRouteManager.commandAudioSource(context), GigaAmModel.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(minimum * 2, 8192));
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("Микрофон недоступен");
            effects = AudioRouteManager.attachEffects(context, recorder, true);
            audio = recorder; recorder.startRecording();
            if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException("Микрофон занят");
            capture=VoiceTelemetry.captureOpened(VoiceTelemetry.GIGA);DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());
            }
            android.util.Log.i("WileyVoice",(source==null?"mic_opened":"pcm_source_ready")+" id="+ticket+" elapsed_ms="+(SystemClock.elapsedRealtime()-startedAt));
            post(ticket, () -> listener.state("Слушаю на телефоне · GigaAM · нажмите ■ для завершения"));
            CountDownLatch prompt = new CountDownLatch(1);
            if (source == null) post(ticket, () -> listener.ready(prompt::countDown)); // Manual sessions preserve their prompt.
            else prompt.countDown(); // Captured command must not be discarded while speaking a prompt.
            short[] buffer = new short[silero != null ? GigaAmSileroVad.HOP : CHUNK];
            long began = 0, promptBegan=SystemClock.elapsedRealtime();
            java.util.ArrayDeque<short[]> preRoll=new java.util.ArrayDeque<>();
            boolean dropped = true, speech = false, ended = false, announced = false;
            long silenceSince = 0, speechStarted = 0, vadDiscarded = 0;
            int preRollSamples = 0;
            long lastLevel=0,lastSpeech=0; NeonWaveMath.LevelNormalizer visualLevel=new NeonWaveMath.LevelNormalizer(); VoiceSpectrum spectrum=listener.wantsSpectrum()?new VoiceSpectrum():null;
            while (!cancelled && !finishing && (began==0 || SystemClock.elapsedRealtime() - began < timeoutMillis)) {
                int n;
                try { n = source == null ? recorder.read(buffer, 0, buffer.length) : source.read(buffer, 100); }
                catch (IllegalStateException error) { if (finishing || cancelled) break; throw error; }
                if (source != null && n == 0) {
                    if (began == 0 && SystemClock.elapsedRealtime() - startedAt >= timeoutMillis) throw new IllegalStateException("Не удалось получить звук микрофона");
                    continue;
                }
                if (source != null && n == -1 && (cancelled || finishing)) break;
                if (n <= 0) { if (finishing || cancelled) break; throw new IllegalStateException("Не удалось получить звук микрофона"); }
                frames++;sampleCount+=n;
                if(frames==1)android.util.Log.i("WileyVoice","pcm_received id="+ticket+" samples="+n);
                if (prompt.getCount() == 0) dropped = false;
                if (dropped) { if(SystemClock.elapsedRealtime()-promptBegan>6500)throw new IllegalStateException("Не удалось завершить голосовую подсказку"); continue; }
                if(began==0){began=SystemClock.elapsedRealtime();android.util.Log.i("WileyVoice","listening_ready id="+ticket+" elapsed_ms="+(began-startedAt));post(ticket,()->listener.state("Говорите сейчас"));}
                vad.measure(buffer, n);
                boolean loud = false;
                long now = SystemClock.elapsedRealtime();
                long endpointClock = now;
                boolean decided = true;
                boolean vadFailed = false;
                if (silero != null) {
                    try {
                        Boolean neural = silero.observe(buffer, n);
                        decided = neural != null;
                        loud = Boolean.TRUE.equals(neural);
                        // Retrospective PCM can be consumed faster than real time.
                        endpointClock = (sampleCount - silero.pending()) * 1000 / GigaAmModel.SAMPLE_RATE;
                    } catch (ReflectiveOperationException | IOException | RuntimeException | LinkageError unavailable) {
                        silero.close();
                        silero = null;
                        silenceSince = 0;
                        speechStarted = now;
                        vadFailed = true;
                        vadBackend = "energy_fallback";
                        android.util.Log.i("WileyVoice", "vad_fallback id=" + ticket + " reason=inference");
                    }
                }
                if (silero == null) loud = vad.isSpeech(speech);
                if(now-lastLevel>=150){lastLevel=now;float level=visualLevel.observe(vad.current);float[] bands=spectrum==null?null:spectrum.analyze(buffer,n);post(ticket,()->{listener.level(level);if(bands!=null)listener.spectrum(bands);});}
                if (loud) {
                    lastSpeech=now;
                    silenceSince = 0;
                    if (!speech) {
                        speech = true; speechStarted = endpointClock;
                        if (sileroPreRoll != null) {
                            if (preRollSamples > 0) kept.add(sileroPreRoll.drain());
                            preRollSamples = 0;
                        } else {
                            kept.addAll(preRoll);
                            preRoll.clear();
                        }
                        android.util.Log.i("WileyVoice","speech_started id="+ticket+" elapsed_ms="+(now-startedAt));
                    }
                    if (!announced) { announced = true; post(ticket, () -> listener.state("Слышу речь · нажмите ■ для завершения")); }
                    kept.add(trim(buffer, n));
                } else if (speech) {
                    kept.add(trim(buffer, n)); // Keep trailing audio up to the endpoint; the decoder tolerates silence.
                    if (decided) {
                        if (silenceSince == 0) silenceSince = endpointClock;
                        else if (endpointClock - silenceSince >= ENDPOINT_SILENCE_MS && endpointClock - speechStarted >= MIN_SPEECH_MS) { ended = true; break; }
                    }
                } else if (sileroPreRoll != null) {
                    sileroPreRoll.append(buffer, 0, n);
                    preRollSamples += n;
                    vadDiscarded += Math.max(0, preRollSamples - 2 * CHUNK);
                    preRollSamples = Math.min(preRollSamples, 2 * CHUNK);
                } else {preRoll.addLast(trim(buffer,n));while(preRoll.size()>2)vadDiscarded+=preRoll.removeFirst().length;}
                if (vadFailed) buffer = new short[CHUNK];
            }
            if (silero != null) { silero.close(); silero = null; }
            stage(ticket,listener,Stage.ENDPOINT,SystemClock.elapsedRealtime());
            if (recorder != null) stop(recorder);
            // Snapshot the accepted queue before inference. No producer can append after seal;
            // consume its finite backlog so speech captured before the endpoint is not discarded.
            if (source != null && !cancelled) {
                source.seal();
                int remaining;
                while (!cancelled && (remaining = source.read(buffer, 0)) > 0) {
                    sampleCount += remaining;
                    if (speech) kept.add(trim(buffer, remaining));
                    else vadDiscarded += remaining;
                }
            }
            stage(ticket,listener,Stage.PCM_DRAINED,SystemClock.elapsedRealtime());
            if (!speech) {
                vadDiscarded += preRollSamples;
                for (short[] chunk : preRoll) vadDiscarded += chunk.length;
            }
            DiagnosticLog.event(DiagnosticJournal.Event.GIGA_VAD_DISCARDED_SAMPLES,vadDiscarded);
            if(began>0)DiagnosticLog.event(DiagnosticJournal.Event.GIGA_CAPTURE_MS,SystemClock.elapsedRealtime()-began);
            if (cancelled) {reason="cancelled";return;}
            if(lastSpeech>0){long endpoint=lastSpeech;post(ticket,()->listener.speechEnded(endpoint));}
            if (kept.isEmpty()) {reason="no_speech"; recognized[0] = ""; return; }
            float[] samples = toFloat(kept);
            double audioMs = samples.length * 1000.0 / GigaAmModel.SAMPLE_RATE;
            DiagnosticLog.event(DiagnosticJournal.Event.GIGA_AUDIO_MS,(long)audioMs);
            android.util.Log.i("WileyVoice","stt_started id="+ticket+" audio_ms="+(long)audioMs+" endpoint="+(ended?"silence":"limit_or_finish"));
            long decodeStarted=SystemClock.elapsedRealtime();
            post(ticket, () -> listener.state("Распознаю речь…"));
            stage(ticket,listener,Stage.SUBMITTED,SystemClock.elapsedRealtime());
            GigaAmSession.Ticket job = runtime.recognize(samples, GigaAmModel.SAMPLE_RATE, audioMs);
            decodeJob = job;
            GigaAmSession.Output output;
            try {
                if (cancelled) abandonDecode(job);
                output = job.result.get(DECODE_WAIT_MS, TimeUnit.MILLISECONDS);
            } catch (CancellationException abandoned) {
                reason = "cancelled";
                return;
            } finally {
                if (!job.result.isDone()) abandonDecode(job);
                decodeJob = null;
            }
            if(output.metrics()!=null){DiagnosticLog.event(DiagnosticJournal.Event.GIGA_DECODE_MS,(long)output.metrics().decodeMs());DiagnosticLog.event(DiagnosticJournal.Event.GIGA_QUEUE_MS,(long)output.metrics().queueMs());}
            if (output.stopped()) {reason="stt_stopped";return;}
            recognized[0] = output.text();
            if(output.metrics()!=null){
                stage(ticket,listener,Stage.QUEUE_DURATION,Math.round(output.metrics().queueMs()));
                stage(ticket,listener,Stage.DECODE_DURATION,Math.round(output.metrics().decodeMs()));
            }
            stage(ticket,listener,Stage.TEXT_READY,SystemClock.elapsedRealtime());
            reason=recognized[0].isEmpty()?"stt_empty":"stt_result";
            android.util.Log.i("WileyVoice","stt_done id="+ticket+" result="+reason+" elapsed_ms="+(SystemClock.elapsedRealtime()-decodeStarted));
        } catch (SecurityException error) { post(ticket, () -> listener.error("Разрешите микрофон для локального распознавания")); }
        catch (Exception failure) {
            reason="stt_or_capture_error";
            String message = failure.getMessage();
            post(ticket, () -> listener.error(message != null && message.matches("(?s).*[А-Яа-яЁё].*") ? message : "Не удалось распознать речь через GigaAM. Проверьте микрофон или выберите другой распознаватель."));
        }
        finally {
            if (effects != null) effects.close();
            if (silero != null) silero.close();
            if (sileroPreRoll != null) sileroPreRoll.clear();
            android.util.Log.i("WileyVoice","session_closed id="+ticket+" reason="+reason+" elapsed_ms="+(SystemClock.elapsedRealtime()-startedAt)+" frames="+frames+" samples="+sampleCount+" peak_rms="+(long)vad.peak+" vad_backend="+vadBackend
                    +(vadBackend.equals("silero")?"":" floor_rms="+(long)vad.floor+" threshold_rms="+(long)vad.threshold));
            if (recorder != null) { stop(recorder); recorder.release(); }
            if(capture!=null){capture.close();DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());}
            if (source != null) {source.close();PcmHandoff.Stats stats=source.stats();DiagnosticLog.event(DiagnosticJournal.Event.PCM_PEAK_BUFFER_SAMPLES,stats.peakQueuedSamples());DiagnosticLog.event(DiagnosticJournal.Event.PCM_DELIVERED_SAMPLES,stats.deliveredSamples());DiagnosticLog.event(DiagnosticJournal.Event.PCM_ACCEPTED_SAMPLES,stats.acceptedSamples());DiagnosticLog.event(DiagnosticJournal.Event.PCM_OVERFLOW_SAMPLES,stats.overflowSamples());DiagnosticLog.event(DiagnosticJournal.Event.PCM_DISCARDED_SAMPLES,stats.discardedSamples());}
            if (externalAudio == source) externalAudio = null;
            if (audio == recorder) audio = null;
            busy.set(false);
            if (recognized[0] != null) { String result = recognized[0]; post(ticket, () -> listener.result(result)); }
            main.post(() -> { if (!closed && ticket == session) listener.finished(); });
        }
    }
    private void stage(int ticket,OfflineSpeechEngine.Listener listener,Stage stage,long value){
        post(ticket,()->listener.gigaStage(stage,value));
    }
    private static short[] trim(short[] source, int length) {
        return PcmChunk.copy(source,length);
    }
    private static float[] toFloat(List<short[]> chunks) {
        long cap = MAX_BUFFER_MS * GigaAmModel.SAMPLE_RATE / 1000;
        long total = 0;
        for (short[] chunk : chunks) total += chunk.length;
        long dropped=0;while (total > cap && !chunks.isEmpty()) { int removed=chunks.remove(0).length;total -= removed;dropped+=removed; }
        DiagnosticLog.event(DiagnosticJournal.Event.GIGA_LIMIT_DISCARDED_SAMPLES,dropped); // Keep the most recent bounded window.
        float[] samples = new float[(int)total]; int offset = 0;
        for (short[] chunk : chunks) for (int i = 0; i < chunk.length; i++) samples[offset++] = chunk[i] / 32768.0f;
        return samples;
    }
    private static void stop(AudioRecord recorder) { try { recorder.stop(); } catch (IllegalStateException ignored) {} }
    void finish() { finishing = true; stopMicrophone(false); }
    void cancel() {
        cancelled = true;
        stopMicrophone(true);
        GigaAmSession.Ticket job = decodeJob;
        if (job != null) abandonDecode(job);
    }
    private static void abandonDecode(GigaAmSession.Ticket job) {
        // Wake the capture worker immediately. Only the ASR worker owns the running JNI call.
        job.cancel();
        job.result.cancel(false);
    }
    private void stopMicrophone(boolean discard) { PcmHandoff input = externalAudio; if (input != null) { if (discard) input.close(); else input.seal(); } AudioRecord recorder = audio; if (recorder != null) { try { recorder.stop(); } catch (IllegalStateException ignored) {} } }
    void close() { closed = true; cancel(); worker.shutdown(); }
    /** Minimal energy endpoint: the noise floor adapts outside speech and freezes inside an utterance. */
    private static final class EnergyVad {
        private double floor;
        EnergyVad(double initialFloor) { floor = initialFloor; }
        private double peak,threshold,current;
        void measure(short[] buffer, int length) {
            double sum = 0;
            for (int i = 0; i < length; i++) sum += (double)buffer[i] * buffer[i];
            current = Math.sqrt(sum / Math.max(1, length));
            peak = Math.max(peak, current);
        }
        boolean isSpeech(boolean insideUtterance) {
            if (!insideUtterance) floor = Math.max(120, floor * 0.92 + current * 0.08);
            threshold=insideUtterance ? Math.max(floor * 1.8, 280) : Math.max(floor * 2.4, 350);
            return current > threshold;
        }
    }
}
