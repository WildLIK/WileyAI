package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.Voice;
import java.util.*;
import java.util.function.Consumer;

/** Uses only installed voices advertised by Android as offline Russian voices. */
final class LocalVoice {
    private final Context context;
    private final SharedPreferences preferences;
    private final Consumer<String> error;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<Runnable> waiting = new ArrayList<>();
    private TextToSpeech tts;
    private boolean ready, closed;
    private int version;
    private String loadedEngine = "", lastUtterance = "";
    private Runnable afterSpeech;
    LocalVoice(Context context, SharedPreferences preferences, Consumer<String> error) { this.context = context.getApplicationContext(); this.preferences = preferences; this.error = error; }
    void ready(Runnable work) {
        if (closed) return;
        if (ready && !loadedEngine.equals(preferences.getString("offline_engine", ""))) { reload(work); return; }
        if (ready) { work.run(); return; }
        waiting.add(work);
        if (tts != null) return;
        final int ticket = ++version;
        String engine = preferences.getString("offline_engine", "");
        loadedEngine = engine;
        tts = new TextToSpeech(context, status -> main.post(() -> {
            if (closed || ticket != version) return;
            if (status != TextToSpeech.SUCCESS) { waiting.clear(); if (tts != null) tts.shutdown(); tts = null; error.accept("Не удалось запустить системную озвучку. Установите TTS-движок с русским офлайн-голосом в настройках Android."); complete(); return; }
            tts.setOnUtteranceProgressListener(new android.speech.tts.UtteranceProgressListener() {
                public void onStart(String id) {}
                public void onDone(String id) { main.post(() -> { if (!closed && ticket == version && id.equals(lastUtterance)) complete(); }); }
                public void onError(String id) { main.post(() -> { if (!closed && ticket == version) { error.accept("Системный TTS-движок не смог озвучить текст. Проверьте установку офлайн-голоса."); complete(); } }); }
            });
            ready = true; List<Runnable> callbacks = new ArrayList<>(waiting); waiting.clear(); for (Runnable callback : callbacks) callback.run();
        }), engine.isEmpty() ? null : engine);
    }
    String engineLabel() {
        if (!ready) return "Системная озвучка Android";
        String selected = preferences.getString("offline_engine", ""); if (selected.isEmpty()) selected = tts.getDefaultEngine();
        for (TextToSpeech.EngineInfo engine : tts.getEngines()) if (engine.name.equals(selected) && engine.label != null && !engine.label.isEmpty()) return engine.label;
        return "Системная озвучка Android";
    }
    String description() { return preferences.getString("voice_engine_description:" + preferences.getString("offline_engine", ""), ""); }
    List<TextToSpeech.EngineInfo> engines() { return ready ? new ArrayList<>(tts.getEngines()) : new ArrayList<>(); }
    void selectEngine(String name, Runnable changed) { preferences.edit().putString("offline_engine", name).remove("offline_voice").apply(); reload(changed); }
    void reload(Runnable changed) {
        version++; waiting.clear(); if (tts != null) { tts.stop(); tts.shutdown(); } tts = null; ready = false; ready(changed);
    }
    List<Voice> voices() {
        List<Voice> voices = new ArrayList<>();
        if (!ready || tts.getVoices() == null) return voices;
        for (Voice voice : tts.getVoices()) if (voice.getLocale().getLanguage().equals("ru") && !voice.isNetworkConnectionRequired()
            && (voice.getFeatures() == null || !voice.getFeatures().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED))) voices.add(voice);
        voices.sort(Comparator.comparing(Voice::getName)); return voices;
    }
    void select(String name) { preferences.edit().putString("offline_voice", name).apply(); }
    void speak(String text) {
        afterSpeech = null;
        speak(text, null);
    }
    void speakCompleted(String text, Runnable done) { afterSpeech = done; speak(text, null); }
    private void complete() { Runnable done = afterSpeech; afterSpeech = null; if (done != null) done.run(); }
    void preview(String name) { speak("Привет! Я Уайли. Так звучит этот голос.", name); }
    private void speak(String text, String preview) {
        ready(() -> {
            List<Voice> voices = voices();
            if (voices.isEmpty()) { error.accept("Установленный русский офлайн-голос не найден. Добавьте его в настройках синтеза речи Android. Сетевой голос автоматически не используется."); complete(); return; }
            String name = preview == null ? preferences.getString("offline_voice", "") : preview; Voice selected = null;
            for (Voice voice : voices) if (voice.getName().equals(name)) selected = voice;
            if (selected == null && !name.isEmpty()) { error.accept("Выбранный офлайн-голос удалён. Выберите другой голос."); complete(); return; }
            if (selected == null) selected = voices.get(0);
            if (tts.setVoice(selected) != TextToSpeech.SUCCESS) { error.accept("Системный движок не смог включить выбранный офлайн-голос"); complete(); return; }
            tts.setSpeechRate(preferences.getFloat("offline_voice_rate", 1));
            tts.setPitch(preferences.getFloat("offline_voice_pitch", 1));
            if (text.isEmpty()) { complete(); return; }
            int maximum = TextToSpeech.getMaxSpeechInputLength();
            for (int start = 0; start < text.length();) {
                int end = Math.min(start + maximum, text.length());
                if (end < text.length()) {
                    int space = text.lastIndexOf(' ', end - 1); if (space > start + maximum / 2) end = space + 1;
                    if (Character.isHighSurrogate(text.charAt(end - 1))) end--;
                }
                lastUtterance = UUID.randomUUID().toString();
                if (tts.speak(text.substring(start, end), start == 0 ? TextToSpeech.QUEUE_FLUSH : TextToSpeech.QUEUE_ADD, null, lastUtterance) == TextToSpeech.ERROR) { error.accept("Движок Android не принял текст для озвучки"); complete(); break; }
                start = end;
            }
        });
    }
    void stop() { afterSpeech = null; lastUtterance = ""; waiting.clear(); if (tts != null) tts.stop(); }
    void close() { closed = true; version++; stop(); if (tts != null) tts.shutdown(); tts = null; }
}
