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
    enum Stage { PREPARE, SUBMIT, SYNTHESIS, FIRST_AUDIO, PLAYING }
    private record Prepared(String requested, long expiresAt) {}
    private record InitCallback(Runnable refresh, boolean refreshOnFailure) {}
    private static final long REUSE_NANOS = java.util.concurrent.TimeUnit.SECONDS.toNanos(15);
    private final Context context;
    private final SharedPreferences preferences;
    private final Consumer<String> error;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<InitCallback> waiting = new ArrayList<>();
    private TextToSpeech tts;
    private boolean ready, closed;
    private boolean reportInitFailure;
    private int version;
    private String loadedEngine = "", lastUtterance = "";
    private Runnable afterSpeech;
    private String firstUtterance = "";
    private Consumer<Stage> timing;
    private Prepared prepared;
    private final java.util.concurrent.atomic.AtomicReference<String> awaitingAudio = new java.util.concurrent.atomic.AtomicReference<>();
    LocalVoice(Context context, SharedPreferences preferences, Consumer<String> error) { this.context = context.getApplicationContext(); this.preferences = preferences; this.error = error; }
    void ready(Runnable work) { ensureReady(new InitCallback(work, false), true); }
    void inspect(Runnable work) { ensureReady(new InitCallback(work, true), false); }
    private void ensureReady(InitCallback work, boolean reportFailure) {
        if (closed) return;
        if (ready && !loadedEngine.equals(preferences.getString("offline_engine", ""))) { reload(work, reportFailure); return; }
        if (ready) { work.refresh().run(); return; }
        waiting.add(work);
        reportInitFailure |= reportFailure;
        if (tts != null) return;
        final int ticket = ++version;
        String engine = preferences.getString("offline_engine", "");
        loadedEngine = engine;
        tts = new TextToSpeech(context, status -> main.post(() -> {
            if (closed || ticket != version) return;
            boolean showFailure = reportInitFailure;
            reportInitFailure = false;
            if (status != TextToSpeech.SUCCESS) {
                if (tts != null) tts.shutdown();
                tts = null;
                android.util.Log.w("WileyTts", "init_failed");
                notifyInitialized(false);
                if (showFailure) error.accept(engine.isEmpty() ? "Не удалось запустить системную озвучку. Проверьте TTS-движок в настройках Android." : "Выбранный движок озвучки недоступен. В разделе «Озвучка» нажмите «Системный» или включите выбранный движок в Android.");
                complete();
                return;
            }
            android.util.Log.i("WileyTts", "init_ok");
            tts.setOnUtteranceProgressListener(new android.speech.tts.UtteranceProgressListener() {
                public void onBeginSynthesis(String id,int sampleRate,int audioFormat,int channels) {
                    main.post(() -> { if (!closed && ticket == version && id.equals(firstUtterance) && timing!=null) timing.accept(Stage.SYNTHESIS); });
                }
                public void onAudioAvailable(String id, byte[] samples) {
                    String expected=awaitingAudio.get();
                    if (samples.length == 0 || !id.equals(expected) || !awaitingAudio.compareAndSet(expected,null)) return;
                    main.post(() -> {
                        if (!closed && ticket == version && id.equals(firstUtterance) && timing!=null) {
                            timing.accept(Stage.FIRST_AUDIO);
                        }
                    });
                }
                public void onStart(String id) { main.post(() -> {
                    if (closed || ticket != version) return;
                    if (id.equals(firstUtterance) && timing!=null) timing.accept(Stage.PLAYING);
                    if (id.equals(lastUtterance)) android.util.Log.i("WileyTts", "utterance_started");
                }); }
                public void onDone(String id) { main.post(() -> { if (!closed && ticket == version && id.equals(lastUtterance)) { lastUtterance=""; android.util.Log.i("WileyTts", "utterance_done"); complete(); } }); }
                public void onError(String id) { main.post(() -> { if (!closed && ticket == version && id.equals(lastUtterance)) { prepared=null;lastUtterance=""; android.util.Log.w("WileyTts", "utterance_error"); error.accept("Системный TTS-движок не смог озвучить текст. Проверьте установку офлайн-голоса."); complete(); } }); }
                public void onStop(String id, boolean interrupted) { main.post(() -> { if (!closed && ticket == version && id.equals(lastUtterance)) { lastUtterance=""; android.util.Log.i("WileyTts", "utterance_stopped"); complete(); } }); }
            });
            ready = true;
            notifyInitialized(true);
        }), engine.isEmpty() ? null : engine);
    }
    private void notifyInitialized(boolean available) {
        List<InitCallback> callbacks = new ArrayList<>(waiting);
        waiting.clear();
        for (InitCallback callback : callbacks) {
            if (available || callback.refreshOnFailure()) callback.refresh().run();
        }
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
    void reload(Runnable changed) { reload(new InitCallback(changed, true), false); }
    private void reload(InitCallback changed, boolean reportFailure) {
        version++; prepared=null; waiting.clear(); reportInitFailure=false; afterSpeech = null; lastUtterance = ""; firstUtterance=""; timing=null; if (tts != null) { tts.stop(); tts.shutdown(); } tts = null; ready = false; ensureReady(changed,reportFailure);
    }
    List<Voice> voices() {
        List<Voice> voices = new ArrayList<>();
        Set<Voice> installed = ready ? tts.getVoices() : null;
        if (installed == null) return voices;
        for (Voice voice : installed) if (voice.getLocale().getLanguage().equals("ru") && !voice.isNetworkConnectionRequired()
            && (voice.getFeatures() == null || !voice.getFeatures().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED))) voices.add(voice);
        voices.sort(Comparator.comparing(Voice::getName)); return voices;
    }
    void select(String name) { prepared=null; preferences.edit().putString("offline_voice", name).apply(); }
    void speak(String text) {
        afterSpeech = null;
        speak(text, null);
    }
    void speakCompleted(String text, Runnable done) { speakTimed(text,done,null); }
    void speakTimed(String text,Runnable done,Consumer<Stage> stages) { afterSpeech=done;speak(text,null,stages); }
    private void complete() { Runnable done = afterSpeech; afterSpeech = null; timing=null; firstUtterance=""; awaitingAudio.set(null); if (done != null) done.run(); }
    void preview(String name) { speak("Привет! Я Уайли. Так звучит этот голос.", name); }
    private void speak(String text, String preview) {
        speak(text,preview,null);
    }
    private void speak(String text,String preview,Consumer<Stage> stages) {
        if(stages!=null)stages.accept(Stage.PREPARE);
        ready(() -> {
            String name = preview == null ? preferences.getString("offline_voice", "") : preview;
            if(!prepareVoice(name,preview==null&&preferences.getBoolean("voice_tts_reuse",true))){complete();return;}
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
                if(start==0){firstUtterance=lastUtterance;timing=stages;awaitingAudio.set(stages!=null?lastUtterance:null);if(stages!=null)stages.accept(Stage.SUBMIT);}
                if (tts.speak(text.substring(start, end), start == 0 ? TextToSpeech.QUEUE_FLUSH : TextToSpeech.QUEUE_ADD, null, lastUtterance) == TextToSpeech.ERROR) { prepared=null;error.accept("Движок Android не принял текст для озвучки"); complete(); break; }
                start = end;
            }
        });
    }
    private boolean prepareVoice(String name,boolean reuse){
        long now=System.nanoTime();
        if(reuse&&prepared!=null&&prepared.requested().equals(name)&&now-prepared.expiresAt()<0)return true;
        prepared=null;
        List<Voice> available=voices();
        if(available.isEmpty()){
            error.accept("Установленный русский офлайн-голос не найден. Добавьте его в настройках синтеза речи Android. Сетевой голос автоматически не используется.");
            return false;
        }
        Voice selected=name.isEmpty()?available.get(0):available.stream().filter(voice->voice.getName().equals(name)).findFirst().orElse(null);
        if(selected==null){error.accept("Выбранный офлайн-голос удалён. Выберите другой голос.");return false;}
        if(tts.setVoice(selected)!=TextToSpeech.SUCCESS){error.accept("Системный движок не смог включить выбранный офлайн-голос");return false;}
        if(reuse)prepared=new Prepared(name,now+REUSE_NANOS);
        return true;
    }
    void stop() { afterSpeech = null; lastUtterance = ""; firstUtterance="";timing=null;awaitingAudio.set(null);waiting.clear(); if (tts != null) tts.stop(); }
    boolean speaking(){return afterSpeech!=null||!lastUtterance.isEmpty();}
    void close() { closed = true; prepared=null; version++; stop(); if (tts != null) tts.shutdown(); tts = null; }
}
