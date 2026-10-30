package ru.wildlik.wileyai.mobile;

import android.content.Intent;
import android.os.*;
import android.speech.*;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;

/** Actual offline recognizer required by the Android voice-interactor contract. */
public final class WileyRecognitionService extends RecognitionService {
    private OfflineSpeechEngine speech; private Callback client; private int generation;
    private interface Remote { void run() throws RemoteException; }
    private void send(Remote work) { try { work.run(); } catch (RemoteException gone) { if (speech != null) speech.cancel(); client = null; } }
    private Bundle bundle(String text) { Bundle value = new Bundle(); value.putStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION, new ArrayList<>(Collections.singletonList(text))); return value; }
    @Override public void onCreate() { super.onCreate(); speech = new OfflineSpeechEngine(this); }
    @Override protected void onStartListening(Intent intent, Callback callback) {
        if (speech.busy() || HandsFreeService.answering()) { send(() -> callback.error(SpeechRecognizer.ERROR_RECOGNIZER_BUSY)); return; }
        String language = intent.getStringExtra(RecognizerIntent.EXTRA_LANGUAGE);
        if (language != null && !language.startsWith("ru")) { send(() -> callback.error(Build.VERSION.SDK_INT >= 31 ? SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED : SpeechRecognizer.ERROR_CLIENT)); return; }
        client = callback; int ticket = ++generation;
        HandsFreeService.pauseExternal(() -> {
            if (client != callback || generation != ticket) { HandsFreeService.resumeExternal(); return; }
            try {
                Path model = VerifiedModelInstaller.active(getFilesDir().toPath().resolve("speech-models")); if (model == null) throw new IllegalStateException();
                speech.start(model, new OfflineSpeechEngine.Listener() {
                    private boolean began;
                    private boolean current() { return client == callback && generation == ticket; }
                    public void state(String text) { if (current() && text.startsWith("Слушаю")) send(() -> callback.readyForSpeech(new Bundle())); }
                    public void partial(String text) { if (!current()) return; if (!began) { began = true; send(callback::beginningOfSpeech); } if (intent.getBooleanExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)) send(() -> callback.partialResults(bundle(text))); }
                    public void result(String text) { if (!current()) return; client = null; if (text.isEmpty()) send(() -> callback.error(SpeechRecognizer.ERROR_NO_MATCH)); else { send(callback::endOfSpeech); send(() -> callback.results(bundle(text))); } }
                    public void error(String text) { if (current()) { client = null; send(() -> callback.error(SpeechRecognizer.ERROR_AUDIO)); } }
                    public void finished() { HandsFreeService.resumeExternal(); }
                });
            } catch (Exception missing) { client = null; send(() -> callback.error(SpeechRecognizer.ERROR_SERVER)); HandsFreeService.resumeExternal(); }
        });
    }
    @Override protected void onStopListening(Callback callback) { speech.finish(); }
    @Override protected void onCancel(Callback callback) { generation++; client = null; speech.cancel(); if (!speech.busy()) HandsFreeService.resumeExternal(); }
    @Override public void onDestroy() { client = null; speech.close(); HandsFreeService.resumeExternal(); super.onDestroy(); }
}
