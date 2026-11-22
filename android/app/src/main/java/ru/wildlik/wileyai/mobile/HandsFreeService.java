package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.*;
import android.media.*;
import android.net.Uri;
import android.os.*;
import java.nio.file.Path;
import java.util.*;

/** User-enabled microphone foreground service. Keyword -> short command -> action/local answer -> spoken reply. */
public final class HandsFreeService extends Service {
    static final String ENABLE = "wiley.assistant.ENABLE", STOP = "wiley.assistant.STOP", SESSION = "wiley.assistant.SESSION", CALL = "wiley.assistant.CALL";
    static final String SETTINGS = "wiley.assistant.SETTINGS";
    static final String RELOAD = "wiley.assistant.RELOAD";
    private static final String ACOUSTIC_STOP = "wiley.assistant.ACOUSTIC_STOP";
    private static final int NOTIFICATION = 77;
    interface Host { void show(String state, String heard, String answer); void choices(List<AppRegistry.App> apps); default void level(float value) {} default void spectrum(float[] bands) {} default void videos(List<YoutubeSearch.Video> videos) {} void launch(Intent intent); void dismiss(); default boolean voiceOverlay(){return false;} default void confirm(String plan,java.util.function.Consumer<Boolean> reply){reply.accept(false);} }
    private static volatile HandsFreeService current; private static Host pendingHost;
    private static long requestSequence,pendingWindowWake;
    private final WakeActivation.Gate wakeWindow=new WakeActivation.Gate();
    private long activeWake, quietUntil, recognitionEpoch;
    private boolean firstWakeCommand;
    private final Runnable retryWake=this::resumeWake;
    private static String lastState = "Голосовая активация выключена";
    private final Handler main = new Handler(Looper.getMainLooper());
    private android.content.SharedPreferences settings; private WakeEngine wake; private OfflineSpeechEngine speech; private GigaAmSpeechEngine gigaAm; private LocalVoice voice; private LocalLlm llm; private AppCatalog apps; private AssistantConversation history; private PcmHandoff pendingWakeAudio;
    private PowerManager.WakeLock lock; private AudioManager audio; private AudioFocusRequest focus;
    private Host host; private boolean destroyed, engaged, launched, externalMic, failed; private int cycle, voiceEpoch; private String heard = "", answer = "", chat = ""; private List<AppRegistry.App> options;
    private boolean conversation,followup,playerAction; private int turns; private long conversationBegan;
    private List<YoutubeSearch.Video> videoOptions;
    private final AppSelection appSelection=new AppSelection();
    private CloudChat cloud;
    private GatewayClient remoteGateway;
    private BrainController brain;
    private TurnTiming turnTiming;
    private java.util.function.Consumer<Boolean> pendingPlan;
    private java.util.List<PersonalPreferences.Memory> pendingMemoryMatches;
    private final Runnable renewal = new Runnable() { public void run() { if (destroyed) return; if (lock != null) lock.acquire(10 * 60 * 1000L); main.postDelayed(this, 5 * 60 * 1000L); } };
    static boolean running() { return current != null && !current.destroyed; }
    static boolean answering() { return running() && current.engaged; }
    static boolean acousticSpeaking() {
        HandsFreeService service = current;
        return service != null && service.voice != null && service.voice.speaking();
    }
    static void refreshAcousticNotice() {
        HandsFreeService service = current;
        if (service != null && !service.destroyed)
            ((NotificationManager)service.getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION, service.notification());
    }
    static String status() { return lastState; }
    static void request(Context context,Host host,boolean conversation,long wakeId) {
        pendingHost=host;pendingWindowWake=wakeId;
        context.startForegroundService(new Intent(context,HandsFreeService.class).setAction(SESSION)
            .putExtra("conversation",conversation).putExtra("wake_id",wakeId).putExtra("session_request",++requestSequence));
    }
    static void detached(Host host) {
        HandsFreeService service=current;
        if(pendingHost==host){
            long wakeId=pendingWindowWake;pendingHost=null;pendingWindowWake=0;
            if(service!=null&&wakeId>0&&service.wakeWindow.matches(wakeId)){
                service.dropPendingWake(4);service.scheduleWake(650);
            }
        }
        if(service!=null&&service.host==host){
            service.host=null;
            if(!service.launched)service.finishRequest();
        }
    }
    static void choose(AppRegistry.App app) { if (current != null && current.appSelection.list(SystemClock.elapsedRealtime()).contains(app)) { String phrase=current.appSelection.phrase(SystemClock.elapsedRealtime()); current.appSelection.clear(); current.options=null; current.open(app,phrase,"tap"); } }
    static void chooseVideo(YoutubeSearch.Video video) { if(current!=null&&current.videoOptions!=null&&current.videoOptions.contains(video))current.playVideo(video,current.cycle); }
    static void stop(Context context) { context.getSharedPreferences("wiley-mobile", MODE_PRIVATE).edit().putBoolean("handsfree_enabled", false).apply(); context.stopService(new Intent(context, HandsFreeService.class)); }
    static void pauseExternal(Runnable after) { if (current == null) { after.run(); return; } current.externalMic = true; current.wake.pause(after); }
    static void resumeExternal() { if (current != null) { current.externalMic = false; current.resumeWake(); } }
    static void reload(Context context) { if (running()) context.startForegroundService(new Intent(context, HandsFreeService.class).setAction(RELOAD)); }
    static void sessionFailed(long wakeId) {
        HandsFreeService service=current;
        if(service==null)return;
        if(wakeId>0){
            if(service.wakeWindow.matches(wakeId)){service.dropPendingWake(3);service.scheduleWake(650);}
        }else if(!service.engaged&&!service.wakeWindow.waiting()){
            service.fail("Android не открыл помощника. Повторно выберите WileyAI в настройках цифрового помощника.");
        }
    }
    @Override public void onCreate() {
        super.onCreate(); current = this; settings = getSharedPreferences("wiley-mobile", MODE_PRIVATE);
        wake = new WakeEngine(this); speech = new OfflineSpeechEngine(this); gigaAm = new GigaAmSpeechEngine(this, GigaAmRuntime.get(this)); voice = new LocalVoice(this, settings, message -> { VoiceDiagnostics.ttsError("ошибка озвучки"); update(message); }); llm = new LocalLlm(this); cloud=new CloudChat(this);remoteGateway=new GatewayClient(this); history = new AssistantConversation(this);voice.ready(()->{});
        apps = new AppCatalog(this, settings, () -> {}); audio = (AudioManager)getSystemService(AUDIO_SERVICE);
        brain=new BrainController(this,apps);
        focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK).setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()).setOnAudioFocusChangeListener(change -> { if (change == AudioManager.AUDIOFOCUS_LOSS && engaged && !playerAction) finishRequest(); }).build();
        lock = ((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "WileyAI:voice-activation"); lock.setReferenceCounted(false);
        ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(new NotificationChannel("voice-activation", "Голосовая активация", NotificationManager.IMPORTANCE_LOW));
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ENABLE : intent.getAction();
        if (STOP.equals(action)) { settings.edit().putBoolean("handsfree_enabled", false).apply(); stopSelf(); return START_NOT_STICKY; }
        if (!WileyVoiceService.selected(this) || checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { fail("Назначьте WileyAI помощником и разрешите микрофон"); return START_NOT_STICKY; }
        try { if (Build.VERSION.SDK_INT >= 30) startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE); else startForeground(NOTIFICATION, notification()); }
        catch (RuntimeException denied) { fail("Android запретил фоновый микрофон. Включите режим из открытого приложения."); return START_NOT_STICKY; }
        main.removeCallbacks(renewal); renewal.run();
        if (SESSION.equals(action)) {
            if(pendingHost!=null&&intent.getLongExtra("session_request",0)==requestSequence){
                Host selected=pendingHost;pendingHost=null;pendingWindowWake=0;
                begin(selected,intent.getBooleanExtra("conversation",false),intent.getLongExtra("wake_id",0));
            }
        }
        else if (RELOAD.equals(action)) wake.pause(this::resumeWake);
        else if (CALL.equals(action)) { if (!WileyVoiceService.invoke()) update("Откройте раздел «Голосовой помощник» и повторите вызов"); }
        else if (ACOUSTIC_STOP.equals(action)) {
            AcousticDiagnostics diagnostics = AcousticDiagnostics.current();
            if (diagnostics != null) diagnostics.stop("notification_stop");
            if (settings.getBoolean("handsfree_enabled", false)) resumeWake();
            else stopSelf();
        }
        else if (settings.getBoolean("handsfree_enabled", false)) resumeWake();
        else stopSelf();
        return settings.getBoolean("handsfree_enabled", false) ? START_STICKY : START_NOT_STICKY;
    }
    private Notification notification() {
        int immutable = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT;
        PendingIntent open = PendingIntent.getActivity(this, 77, new Intent(this, MainActivity.class).setAction(SETTINGS), immutable);
        PendingIntent stop = PendingIntent.getService(this, 78, new Intent(this, HandsFreeService.class).setAction(STOP), immutable);
        PendingIntent speak = PendingIntent.getService(this, 79, new Intent(this, HandsFreeService.class).setAction(CALL), immutable);
        String title = AcousticDiagnostics.capturing() ? "Уайли · акустическая диагностика активна" : "Уайли · голосовой помощник";
        Notification.Builder note = new Notification.Builder(this, "voice-activation").setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle(title).setContentText(lastState).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).setCategory(Notification.CATEGORY_SERVICE).addAction(new Notification.Action.Builder(null, "Сказать команду", speak).build()).addAction(new Notification.Action.Builder(null, "Остановить", stop).build());
        if (AcousticDiagnostics.capturing()) {
            PendingIntent stopRecording = PendingIntent.getService(this, 80, new Intent(this, HandsFreeService.class).setAction(ACOUSTIC_STOP), immutable);
            note.addAction(new Notification.Action.Builder(null, "Остановить запись", stopRecording).build());
        }
        return note.build();
    }
    private void update(String state) { lastState = state; if (!destroyed) { Host visible = host == null ? pendingHost : host; if (visible != null) visible.show(state, heard, answer); ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION, notification()); } }
    private void fail(String state) { failed = true; update(state); settings.edit().putBoolean("handsfree_enabled", false).apply(); stopSelf(); }
    private void scheduleWake(long millis){main.removeCallbacks(retryWake);main.postDelayed(retryWake,millis);}
    private void dropPendingWake(int reason){
        WakeActivation pending=wakeWindow.take();
        if(pending!=null)DiagnosticLog.event(DiagnosticJournal.Event.WAKE_WINDOW_OUTCOME,reason,pending.id());
        AcousticDiagnostics acoustic = AcousticDiagnostics.current();
        if (pending != null && acoustic != null) acoustic.window(pending.id(),
                switch (reason) { case 2 -> "timeout"; case 3 -> "android_rejected"; case 4 -> "cancelled"; default -> "busy"; });
        if(pendingWakeAudio!=null){pendingWakeAudio.close();pendingWakeAudio=null;}
    }
    private void resumeWake() {
        if (destroyed || engaged || externalMic || wake.busy() || wakeWindow.waiting()) return;
        long remaining=quietUntil-SystemClock.elapsedRealtime();
        if(remaining>0||speech.busy()||gigaAm.busy()||voice.speaking()){scheduleWake(Math.max(100,remaining));return;}
        if (!settings.getBoolean("handsfree_enabled", false)) { stopSelf(); return; }
        if (!WileyVoiceService.selected(this)) { settings.edit().putBoolean("handsfree_enabled", false).apply(); stopSelf(); return; }
        try {
            Path model = VerifiedModelInstaller.active(getFilesDir().toPath().resolve("speech-models")); if (model == null) throw new IllegalStateException();
            String phrase = settings.getString("wake_phrase", WakeSettings.defaultPhrase(this)); if (!WakePhrase.valid(phrase)) phrase = WakePhrase.DEFAULT;
            String selected = WakePhrase.label(phrase); update("Загружаю голосовую активацию…");
            boolean usePcm = settings.getInt("asr_engine", 0) == 3;
            boolean recoverPrefix = settings.getBoolean(WakeFinalPrefix.PREFERENCE,false);
            wake.start(model, phrase, () -> update("Скажите «" + selected + "»"), usePcm, recoverPrefix, (event,pcm) -> {
                long id=event.id();
                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_CANDIDATE_AT_MS,event.detectedAt(),id);
                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_CANDIDATE_VARIANT,event.variant(),id);
                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_CANDIDATE_CONF_MILLI,event.confidenceMilli(),id);
                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_CANDIDATE_LAG_MS,event.lagMillis(),id);
                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_CANDIDATE_FINAL,event.conversation()?2:1,id);
                boolean speaking=voice.speaking();
                DiagnosticLog.event(DiagnosticJournal.Event.WAKE_SERVICE_STATE,1|(engaged?2:0)|(speaking?4:0)|(externalMic?8:0)|(locked()?16:0),id);
                if (destroyed || engaged || externalMic || speaking || !settings.getBoolean("handsfree_enabled", false) || !wakeWindow.reserve(event)) {
                    if(pcm!=null)pcm.close();
                    DiagnosticLog.event(DiagnosticJournal.Event.WAKE_WINDOW_OUTCOME,5,id);
                    AcousticDiagnostics observer = AcousticDiagnostics.current();
                    if (observer != null) observer.window(id, "busy");
                    return;
                }
                DiagnosticLog.event(DiagnosticJournal.Event.VOICE_WAKE,event.conversation()?1:0,id);update("Вызываю Уайли…");
                pendingWakeAudio=pcm;
                main.postDelayed(()->{if(wakeWindow.matches(id)){dropPendingWake(2);scheduleWake(100);}},15000);
                if (!WileyVoiceService.invoke(event.conversation(),id)) {dropPendingWake(3);fail("Служба Android отключена. Повторно выберите WileyAI в настройках цифрового помощника.");}
            }, message -> { fail(message); }, () -> {if(!engaged&&!destroyed&&!wakeWindow.waiting())scheduleWake(100);});
        } catch (Exception problem) { fail("Установите русский комплект Vosk в «Компонентах»"); }
    }
    private void begin(Host selected,boolean dialogue,long wakeId) {
        if(wakeId!=0&&!(engaged&&wakeId==activeWake)&&!wakeWindow.matches(wakeId)){
            if(!engaged||host!=selected)selected.dismiss();
            return;
        }
        if (externalMic) {dropPendingWake(5);selected.show("Микрофон занят другим распознавателем. Повторите вызов позже.", "", ""); return;}
        if(engaged){host=selected;host.show(lastState,heard,answer);if(options!=null)host.choices(options);return;}
        AcousticDiagnostics acoustic = AcousticDiagnostics.current();
        if (acoustic != null) acoustic.cancelAnalysis();
        if(wakeId==0)dropPendingWake(4);
        WakeActivation decision=wakeWindow.take();
        activeWake=decision==null?0:decision.id();firstWakeCommand=activeWake!=0;
        if(decision!=null){
            DiagnosticLog.event(DiagnosticJournal.Event.WAKE_WINDOW_OUTCOME,1,activeWake);
            if (acoustic != null) acoustic.window(activeWake, "opened");
            DiagnosticLog.event(DiagnosticJournal.Event.WAKE_WINDOW_LATENCY_MS,SystemClock.elapsedRealtime()-decision.detectedAt(),activeWake);
        }
        DiagnosticLog.event(DiagnosticJournal.Event.VOICE_BEGIN,0,activeWake);
        cycle++; int ticket = cycle; speech.cancel(); gigaAm.cancel(); llm.cancel(); cloud.cancel();remoteGateway.cancel(); voice.stop(); engaged = true; launched = false; host = selected; options = appSelection.active(SystemClock.elapsedRealtime())?new ArrayList<>(appSelection.list(SystemClock.elapsedRealtime())):null; videoOptions=null; chat = ""; heard = ""; answer = "";
        conversation=dialogue; followup=false; turns=0;conversationBegan=SystemClock.elapsedRealtime();
        update("Готовлю микрофон…"); audio.requestAudioFocus(focus);
        if (settings.getInt("asr_engine", 0) == 3) GigaAmRuntime.get(this).prepare(); // weights warm up while the panel opens
        PcmHandoff captured=pendingWakeAudio;pendingWakeAudio=null;
        if(captured!=null && !dialogue && settings.getInt("asr_engine",0)==3 && captured.isActive()) {
            listen(ticket,captured,decision==null?-1:decision.detectedAt());
        }
        else {if(captured!=null)captured.close();wake.pause(() -> { if (valid(ticket)) { if(dialogue)process("давай поговорим",ticket);else listen(ticket); } });}
    }
    private boolean valid(int ticket) { return !destroyed && engaged && cycle == ticket; }
    private void listen(int ticket) { listen(ticket,null,-1); }
    private void listen(int ticket, PcmHandoff captured, long wakeAt) {
        if (!valid(ticket)) {if(captured!=null)captured.close();return;}
        if (speech.busy() || gigaAm.busy()) {
            long waitingEpoch=recognitionEpoch;
            main.postDelayed(()->{if(waitingEpoch==recognitionEpoch)listen(ticket,captured,wakeAt);else if(captured!=null)captured.close();},100);
            return;
        }
        long epoch=++recognitionEpoch;
        try {
            int waiting=followup?ConversationMode.waitMillis(conversation,true,settings.getInt("followup_seconds",8),settings.getInt("conversation_seconds",30),turns,SystemClock.elapsedRealtime()-conversationBegan):15000;
            if(waiting==0){if(captured!=null)captured.close();finishRequest();return;}
            String engine = settings.getInt("asr_engine", 0) == 3 ? "GigaAM" : settings.getInt("asr_engine", 0) == 0 ? "Vosk" : "Android";
            long sttBegan = SystemClock.elapsedRealtime();
            TurnTiming timing = new TurnTiming();
            turnTiming = timing;
            if(activeWake!=0)DiagnosticLog.event(DiagnosticJournal.Event.WAKE_TURN_LINK,timing.id(),activeWake);
            timing.mark(DiagnosticJournal.Event.TURN_BEGIN_MS);
            VoiceDiagnostics.begin(ticket); VoiceDiagnostics.stt(ticket, engine, "слушаю", false, 0);
            OfflineSpeechEngine.Listener listener = new OfflineSpeechEngine.Listener() {
                public void speechEnded(long stamp){if(currentTurn())timing.markAt(DiagnosticJournal.Event.TURN_SPEECH_END_MS,stamp);}
                public void gigaStage(GigaAmSpeechEngine.Stage stage,long value){
                    if(!currentTurn())return;
                    switch(stage){
                        case ENDPOINT -> timing.markAt(DiagnosticJournal.Event.TURN_ENDPOINT_MS,value);
                        case PCM_DRAINED -> timing.markAt(DiagnosticJournal.Event.TURN_PCM_DRAINED_MS,value);
                        case SUBMITTED -> timing.markAt(DiagnosticJournal.Event.TURN_STT_SUBMIT_MS,value);
                        case QUEUE_DURATION -> timing.duration(DiagnosticJournal.Event.TURN_STT_QUEUE_DURATION_MS,value);
                        case DECODE_DURATION -> timing.duration(DiagnosticJournal.Event.TURN_STT_DECODE_DURATION_MS,value);
                        case TEXT_READY -> timing.markAt(DiagnosticJournal.Event.TURN_STT_TEXT_READY_MS,value);
                    }
                }
                private long lastLevelEvent;
                private boolean currentTurn(){return valid(ticket)&&recognitionEpoch==epoch;}
                public void level(float value){if(currentTurn()&&host!=null)host.level(value);long now=SystemClock.elapsedRealtime();if(now-lastLevelEvent>=1000){lastLevelEvent=now;DiagnosticLog.event(DiagnosticJournal.Event.VOICE_LEVEL_MILLI,(long)(Math.max(0,Math.min(1,value))*1000));}}
                public boolean wantsSpectrum(){return host!=null && host.voiceOverlay();}
                public void spectrum(float[] bands){if(currentTurn()&&host!=null)host.spectrum(bands);}
                public void ready(Runnable startMicrophone) {
                    if (!currentTurn()) return;
                    if (!settings.getBoolean("assistant_listening_prompt", true)) { startMicrophone.run(); return; }
                    update("Распознаватель готов…");
                    java.util.concurrent.atomic.AtomicBoolean once = new java.util.concurrent.atomic.AtomicBoolean();
                    Runnable begin = () -> { if (currentTurn() && once.compareAndSet(false, true)) { voice.stop(); startMicrophone.run(); } };
                    voice.speakCompleted("Слушаю", begin); main.postDelayed(begin, 5000);
                }
                public void state(String text) { if (currentTurn()) { update(text.startsWith("Слушаю") ? followup?"Слушаю следующий вопрос · "+waiting/1000+" сек.":"Слушаю команду…" : text); if (captured==null && text.startsWith("Слушаю")) { ToneGenerator signal = new ToneGenerator(AudioManager.STREAM_MUSIC, 35); signal.startTone(ToneGenerator.TONE_PROP_BEEP, 110); main.postDelayed(signal::release, 200); } } }
                public void partial(String text) { if (currentTurn()) { heard = text; update("Слушаю…"); } }
                public void result(String text) {
                    if(!currentTurn())return;
                    recognitionEpoch++;
                    timing.mark(DiagnosticJournal.Event.TURN_STT_DONE_MS);
                    boolean hadWords=!text.isBlank();
                    if(firstWakeCommand){
                        firstWakeCommand=false;
                        String phrase=settings.getString("wake_phrase",WakeSettings.defaultPhrase(HandsFreeService.this));
                        text=PhoneCommands.stripAddress(WakePhrase.removeLeadingWake(text,phrase));
                        text=WakePhrase.removeConfusableWake(text,phrase,candidate->{
                            PhoneCommands.Action command=PhoneCommands.parse(candidate,true);
                            return command!=null&&!command.kind.equals("open")&&!command.kind.equals("media_search")
                                &&!command.kind.equals("media_play_search")&&!StructuredActionAdapter.requiresPlan(candidate);
                        });
                        if(text.isEmpty()&&hadWords){
                            wakeResult(7);
                            update("Слушаю команду…");
                            wake.pause(()->{if(valid(ticket))listen(ticket);});
                            return;
                        }
                    }
                    VoiceDiagnostics.stt(ticket,engine,text.isBlank()?"пустой результат":"готово",!text.isBlank(),SystemClock.elapsedRealtime()-sttBegan);
                    if(text.isBlank()){
                        wakeResult(1);
                        respond("Не удалось распознать речь. Попробуйте ещё раз.",ticket,false,false);
                        return;
                    }
                    timing.mark(DiagnosticJournal.Event.TURN_COMMAND_TEXT_MS);
                    heard=text;followup=false;update("Поняла: «"+text+"»");
                    if(videoOptions!=null){
                        int choice=option(text);
                        if(text.matches("да|да включи|включи|включай|включи первое|первое|первое видео"))choice=0;
                        if(choice>=0&&choice<videoOptions.size())playVideo(videoOptions.get(choice),ticket);
                        else if(text.matches("нет|отмена|не включай|закончили")){videoOptions=null;respond("Хорошо, видео не включаю.",ticket,false);}
                        else{videoOptions=null;process(text,ticket);}
                        return;
                    }
                    if(appSelection.active(SystemClock.elapsedRealtime()))handleAppSelection(text,ticket);
                    else process(text,ticket);
                }
                public void error(String text) {
                    if(!currentTurn())return;
                    recognitionEpoch++;
                    VoiceDiagnostics.stt(ticket,engine,"ошибка распознавания",false,SystemClock.elapsedRealtime()-sttBegan);
                    wakeResult(5);
                    respond(text,ticket,false);
                }
                public void finished() {}
            };
            if (settings.getInt("asr_engine", 0) == 3) {
                if (captured != null) {
                    if (wakeAt >= 0) DiagnosticLog.event(DiagnosticJournal.Event.WAKE_GIGA_HANDOFF_MS,
                        SystemClock.elapsedRealtime() - wakeAt,activeWake);
                    gigaAm.startFromPcm(waiting,listener,captured);
                } else gigaAm.start(waiting, listener);
                return;
            }
            if(captured!=null)captured.close();
            Path model = VerifiedModelInstaller.active(getFilesDir().toPath().resolve("speech-models")); if (model == null) throw new IllegalStateException();
            speech.start(model, listener, waiting);
        } catch (Exception missing) { if(captured!=null)captured.close();respond("Не удалось подготовить распознавание речи. Повторите запрос.", ticket,false); }
    }
    private void handleAppSelection(String text,int ticket){
        long now=SystemClock.elapsedRealtime();int choice=appSelection.select(text,now);
        if(choice==-2){appSelection.clear();options=null;respond("Хорошо, не открываю.",ticket,false);return;}
        if(choice>=0){AppRegistry.App chosen=appSelection.list(now).get(choice);String phrase=appSelection.phrase(now);appSelection.clear();options=null;open(chosen,phrase,"voice");return;}
        if(choice==-3){options=null;process(text,ticket);return;}
        if(PhoneCommands.parse(text,true)!=null && !text.toLowerCase(Locale.ROOT).matches(".*(?:перв|втор|трет|четвер|пят|последн).*")){appSelection.clear();options=null;process(text,ticket);return;}
        options=new ArrayList<>(appSelection.list(now));String message="Уточните номер или название приложения, либо скажите отмена.";update(message);speak(message,ticket,()->listen(ticket));
    }
    static int option(String text) { String value = text.toLowerCase(Locale.ROOT).trim(); String[] names = {"первый", "второй", "третий", "четвертый", "пятый"}; for (int i = 0; i < names.length; i++) if (value.replace('ё','е').matches("(?:вариант )?(?:" + names[i] + "|" + (i + 1) + ")")) return i; return -1; }
    private boolean locked() { return ((KeyguardManager)getSystemService(KEYGUARD_SERVICE)).isDeviceLocked(); }
    private void process(String text, int ticket) {
        if(pendingPlan!=null){markLocalRoute();String choice=text.toLowerCase(Locale.ROOT).trim();if(choice.matches("да|выполни|выполняй|подтверждаю|согласен|хорошо")){finishPlanConfirmation(true);return;}if(choice.matches("нет|отмена|отмени|стоп|закончили")){finishPlanConfirmation(false);return;}finishPlanConfirmation(false);return;}
        if(pendingMemoryMatches!=null){
            var matches=pendingMemoryMatches;pendingMemoryMatches=null;
            if(text.toLowerCase(Locale.ROOT).matches("отмена|нет|отмени")){respond("Хорошо, ничего не удаляю.",ticket,false,false);return;}
            int index=MemoryCommand.selection(text);
            if(index<0||index>=matches.size()){respond("Не удалось выбрать запись. Повторите запрос.",ticket,false,false);return;}
            confirmMemoryDelete(matches.get(index),ticket);return;
        }
        int blocked=PhoneCommands.blockedVoice(text);
        if(blocked!=0){
            wakeResult(4);
            respond(blocked==1?"Хорошо, ничего не делаю.":"Уточните команду.",ticket,false,false);
            return;
        }
        PersonalPreferences personal=new PersonalPreferences(this);
        String identity=ProfileIdentity.answer(text,personal.name(),personal.address());
        if(identity!=null){markLocalRoute();respond(locked()?"Разблокируйте телефон для просмотра профиля.":identity,ticket,false,false);return;}
        MemoryCommand.Request memoryRequest=MemoryCommand.parse(text);
        if(memoryRequest!=null){markLocalRoute();handleMemoryCommand(memoryRequest,ticket);return;}
        if(MemoryCommand.ambiguousMutation(text)){respond("Для изменения памяти скажите запомни, что, или забудь, что.",ticket,false,false);return;}
        Host screenHost=host;
        update("Думаю…");
        if(ScreenDispatcher.dispatch(this,apps,text,()->valid(ticket)&&host==screenHost,screenHost!=null&&screenHost.voiceOverlay(),reply->respond(reply,ticket,true,false)))return;
        VoiceDiagnostics.route("", "планировщик", "не распознано как запрос к экрану");
        history.submit(text, (id, context) -> {
            if (!valid(ticket)) return; chat = id; dispatch(text,ticket,context);
        }, error -> {
            if (!valid(ticket)) return; chat = "";
            if ((!StructuredActionAdapter.requiresPlan(text)&&PhoneCommands.parse(text,true) != null) || ConversationMode.parse(text) != 0)
                dispatch(text,ticket,Collections.emptyList());
            else respond(error,ticket,false);
        });
    }
    private void handleMemoryCommand(MemoryCommand.Request request,int ticket){
        if(locked()||host==null){respond("Разблокируйте телефон для работы с памятью.",ticket,false,false);return;}
        PersonalPreferences memory=new PersonalPreferences(this);
        if(request.kind()==MemoryCommand.Kind.SAVE){
            confirmMemory("Запомнить: "+request.text(),ticket,()->memory.saveMemory(null,request.text()),"Воспоминание сохранено.");return;
        }
        java.util.List<PersonalPreferences.Memory> records;
        try{records=memory.memories();}catch(IllegalStateException failure){respond("Не удалось прочитать память.",ticket,false,false);return;}
        if(request.kind()==MemoryCommand.Kind.LIST){
            String result=records.isEmpty()?"Воспоминаний пока нет.":"Помню: "+android.text.TextUtils.join(". ",records.stream().map(PersonalPreferences.Memory::text).toArray(String[]::new));
            respond(result,ticket,false,false);return;
        }
        java.util.List<PersonalPreferences.Memory> matches=new java.util.ArrayList<>();
        for(var record:records)if(MemoryCommand.matches(record.text(),request.text()))matches.add(record);
        if(matches.isEmpty()){respond("Подходящее воспоминание не найдено.",ticket,false,false);return;}
        if(matches.size()==1){confirmMemoryDelete(matches.get(0),ticket);return;}
        pendingMemoryMatches=matches.subList(0,Math.min(5,matches.size()));
        StringBuilder prompt=new StringBuilder("Нашла несколько записей. Скажите номер или отмена. ");
        for(int i=0;i<pendingMemoryMatches.size();i++)prompt.append(i+1).append(": ").append(pendingMemoryMatches.get(i).text()).append(". ");
        answer=prompt.toString();update("Выберите воспоминание");speak(answer,ticket,()->listen(ticket));
    }
    private void confirmMemoryDelete(PersonalPreferences.Memory record,int ticket){
        confirmMemory("Удалить воспоминание: "+record.text(),ticket,()->new PersonalPreferences(this).removeMemory(record.id()),"Воспоминание удалено.");
    }
    private void confirmMemory(String prompt,int ticket,Runnable action,String success){
        Host surface=host;
        if(surface==null||!valid(ticket))return;
        pendingPlan=approved->{
            if(!valid(ticket))return;
            if(!approved){respond("Отменено.",ticket,false,false);return;}
            try{action.run();respond(success,ticket,false,false);}
            catch(IllegalStateException failure){respond("Не удалось изменить память.",ticket,false,false);}
        };
        java.util.function.Consumer<Boolean> expected=pendingPlan;
        surface.confirm(prompt,approved->{if(valid(ticket)&&pendingPlan==expected)finishPlanConfirmation(approved);});
        answer=prompt;update("Подтвердите: «да» или «отмена»");
        speak(prompt+". Подтвердите: да или отмена.",ticket,()->listen(ticket));
    }
    private void dispatch(String text,int ticket,List<LocalChatRepository.Message> context) {
            if (!valid(ticket)) return; PhoneCommands.Action action = StructuredActionAdapter.requiresPlan(text)?null:PhoneCommands.parse(text, true);
            int mode=ConversationMode.parse(text);
            if(mode!=0||action!=null)markLocalRoute();
            if(mode==ConversationMode.START){conversation=true;respond("Давай поговорим. Скажи, что тебя интересует. Чтобы закончить, скажи «закончили».",ticket);return;}
            if(mode==ConversationMode.END){conversation=false;respond("Хорошо, закончили. Позови меня, когда понадоблюсь.",ticket,false);return;}
            if (action != null) {
                if (action.kind.equals("open")) { if (locked()) { respond("Разблокируйте телефон для открытия приложения.", ticket); return; } openTarget(action.value, ticket); }
                else if(action.kind.equals("media_search")||action.kind.equals("media_play_search")){
                    if(locked()||host==null){respond("Разблокируйте телефон для поиска музыки и видео.",ticket);return;}
                    update("Ищу музыку или видео…");
                    MediaNavigation.executeDetailed(this,action,intent->{if(!valid(ticket)||host==null||locked())throw new IllegalStateException();launched=true;host.launch(intent);},(display,spoken)->respond(display,spoken,ticket),videos->{
                        if(!valid(ticket)||host==null)return;videoOptions=videos;host.videos(videos);
                        answer="1. "+videos.get(0).title()+"\n"+videos.get(0).channel();update("Включить найденное видео?");
                        speak("Нашла: "+videos.get(0).title()+". Включить? Скажи «да», номер другого варианта или «отмена».",ticket,()->listen(ticket));
                    });
                }
                else { playerAction=action.kind.equals("media")&&action.value.matches("play|next|previous");java.util.function.Consumer<Intent> openPlayer=locked()?null:intent->{if(!valid(ticket)||host==null||locked())throw new IllegalStateException();launched=true;host.launch(intent);};PhoneActionCore.execute(this, action, text, openPlayer, ()->valid(ticket), (display,spoken) -> {playerAction=false;respond(display, spoken, ticket);}); }
            } else if (locked()) respond("Разблокируйте телефон для разговора с моделью. Время, музыка и громкость доступны сразу.", ticket);
            else if (text.toLowerCase(Locale.ROOT).matches(".*на (?:пк|компьютере)[.! ]*$")) respond("Сейчас я управляю телефоном. Режим компьютера доступен в приложении.", ticket);
            else {
                try {
                    wakeResult(3);
                    ModelManager manager=new ModelManager(this);
                    if(manager.automatic()||manager.toolsAllowed()||manager.selected()==BrainProvider.Kind.ACCOUNT_OAUTH){
                        Host surface=host;brain.generate(context,new BrainController.Host(){
                            public boolean active(){return valid(ticket);}
                            public void state(String value){if(valid(ticket)){if(value.startsWith("Выполняю:"))playerAction=true;update(value);}}
                            public void confirm(String plan,java.util.function.Consumer<Boolean> reply){if(!valid(ticket)||surface==null){reply.accept(false);return;}pendingPlan=reply;surface.confirm(plan,approved->{if(valid(ticket)&&pendingPlan==reply)finishPlanConfirmation(approved);});answer=plan;update("Подтвердите план: «да» или «отмена»");speak(plan+". Выполнить? Скажите да или отмена.",ticket,()->listen(ticket));}
                            public void launch(Intent intent){if(!valid(ticket)||surface==null||locked())throw new IllegalStateException();launched=true;surface.launch(intent);}
                            public void done(String value){if(!valid(ticket))return;playerAction=false;VoiceDiagnostics.answer(ticket, "получен");respond(value,ticket);}
                            public void error(String value){if(!valid(ticket))return;playerAction=false;VoiceDiagnostics.answer(ticket, value.contains("отмен") ? "отменён" : "ошибка модели");respond(value,ticket);}
                            public void finished(){}
                        },turnTiming==null?new TurnTiming():turnTiming);return;
                    }
                    TurnTiming timing=turnTiming;
                    if(timing!=null){timing.intent(3);timing.route(4);}
                    boolean gateway=GatewayClient.enabled(this),remote=CloudChat.enabled(this);Path model = gateway||remote?null:LlmModels.readActive(getFilesDir().toPath().resolve("llm-models")); if (!gateway&&!remote&&model == null) { respond("Установите разговорную модель или подключите облачный чат в разделе «Компоненты». Команды телефону уже доступны.", ticket); return; }
                    update(gateway?"Отвечаю через WileyAI Gateway…":remote?"Отвечаю через выбранный облачный сервис…":"Отвечаю на телефоне…");
                    LocalLlm.Listener listener = new LocalLlm.Listener() {
                        private boolean first;
                        public void state(String text) { if (valid(ticket)) update(text); }
                        public void partial(String text) { if (valid(ticket)) {
                            if(!first&&!text.isEmpty()){first=true;if(timing!=null)timing.mark(DiagnosticJournal.Event.TURN_MODEL_FIRST_MS);}
                            answer = text; update("Отвечаю…");
                        } }
                        public void done(String text, boolean stopped) { if (valid(ticket)) respond(text.isEmpty() ? "Не удалось получить ответ. Повторите вопрос." : text, ticket,true,!(gateway&&remoteGateway.savedResponse())); }
                        public void error(String text) { if (valid(ticket)) respond(text, ticket); } public void finished() {}
                    };
                    if(timing!=null)timing.mark(DiagnosticJournal.Event.TURN_MODEL_BEGIN_MS);
                    if(gateway)remoteGateway.generate(chat,context,listener);else if(remote)cloud.generate(context,listener);else llm.generate(model,LocalLlm.prompt(context,new PersonalPreferences(this).localResponseContext(text)),listener);
                } catch (Exception missing) { respond("Не удалось открыть разговорную модель. Проверьте её в приложении.", ticket); }
            }
    }
    private void wakeResult(int code){
        if(activeWake!=0)DiagnosticLog.event(DiagnosticJournal.Event.WAKE_RESULT,code,activeWake);
    }
    private void markLocalRoute(){
        wakeResult(2);
        if(turnTiming!=null){turnTiming.intent(1);turnTiming.route(1);}
    }
    private void openTarget(String target, int ticket) {
        apps.resolve(target, matches -> {
            if (!valid(ticket)) return;
            if (matches.size() == 1) { open(matches.get(0)); return; }
            if (matches.size() > 1) { options = new ArrayList<>(matches.subList(0, Math.min(5, matches.size()))); appSelection.offer(options,SystemClock.elapsedRealtime(),target); if (host != null) host.choices(options); StringBuilder prompt = new StringBuilder("Какое приложение? "); for (int i = 0; i < options.size(); i++) prompt.append(i+1).append(": ").append(options.get(i).label()).append(". "); prompt.append("Скажите номер."); speak(prompt.toString(), ticket, () -> listen(ticket)); return; }
            String url = target.matches("(?i)^https?://[^\\s]+$") ? target : "";
            if (url.isEmpty()) {
                List<AppRegistry.App> suggestions=AppRegistry.suggest(apps.entries(),target);
                if(!suggestions.isEmpty()){
                    options=new ArrayList<>(suggestions);appSelection.offer(options,SystemClock.elapsedRealtime(),target);if(host!=null)host.choices(options);
                    StringBuilder prompt=new StringBuilder(options.size()==1?"Нашла похожее приложение. Скажите да или отмена. ":"Есть похожие названия. ");for(int i=0;i<options.size();i++)prompt.append(i+1).append(": ").append(options.get(i).label()).append(". ");prompt.append("Скажите номер или выберите на экране.");
                    speak(prompt.toString(),ticket,()->listen(ticket));return;
                }
                respond("Приложение не найдено. Скажите его название иначе или добавьте название в «Команды → Мои приложения».", ticket); return;
            }
            try { Uri uri = Uri.parse(url); if (uri.getHost() == null || uri.getUserInfo() != null || locked() || host == null) throw new IllegalStateException(); launched = true; host.launch(new Intent(Intent.ACTION_VIEW, uri)); respond("Открываю сайт на телефоне.", ticket); } catch (Exception failed) { launched = false; respond("Не удалось открыть сайт. Проверьте адрес и разблокируйте телефон.", ticket); }
        });
    }
    private void open(AppRegistry.App app) { open(app,"",""); }
    private void open(AppRegistry.App app,String phrase,String source) {
        int ticket = cycle; if (!valid(ticket)) return;
        if (locked() || host == null) { respond("Разблокируйте телефон и повторите команду открытия.", ticket); return; }
        try {
            ComponentName component = new ComponentName(app.packageName(), app.activity()); ActivityInfo actual = getPackageManager().getActivityInfo(component, 0);
            if (!actual.enabled || !actual.exported || !actual.applicationInfo.enabled) throw new IllegalStateException();
            Intent intent = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setComponent(component).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            long requestedAt=System.currentTimeMillis();launched = true; host.launch(intent); if(!phrase.isEmpty())main.postDelayed(()->rememberVerifiedLaunch(app,phrase,source,requestedAt),2500); respond("Открываю «" + app.label() + "» на телефоне.", ticket);
        } catch (Exception failed) { launched = false; respond("Не удалось открыть приложение. Проверьте его доступность.", ticket); }
    }
    private void rememberVerifiedLaunch(AppRegistry.App app,String phrase,String source,long requestedAt){
        try{
            android.app.AppOpsManager ops=(android.app.AppOpsManager)getSystemService(APP_OPS_SERVICE);
            if(ops.checkOpNoThrow(android.app.AppOpsManager.OPSTR_GET_USAGE_STATS,android.os.Process.myUid(),getPackageName())!=android.app.AppOpsManager.MODE_ALLOWED)return;
            android.app.usage.UsageStatsManager usage=(android.app.usage.UsageStatsManager)getSystemService(USAGE_STATS_SERVICE);
            android.app.usage.UsageEvents events=usage.queryEvents(requestedAt,System.currentTimeMillis()+1);android.app.usage.UsageEvents.Event event=new android.app.usage.UsageEvents.Event();boolean observed=false;
            while(events.hasNextEvent()){events.getNextEvent(event);if(event.getEventType()==android.app.usage.UsageEvents.Event.ACTIVITY_RESUMED&&app.packageName().equals(event.getPackageName())&&app.activity().equals(event.getClassName()))observed=true;}
            if(!observed)return;ActivityInfo info=getPackageManager().getActivityInfo(new ComponentName(app.packageName(),app.activity()),0);if(!info.enabled||!info.exported||!info.applicationInfo.enabled)return;
            new AppNameMemory(settings).record(phrase,app,source);
        }catch(Exception ignored){ /* No verified launch means no learning. */ }
    }
    private void playVideo(YoutubeSearch.Video video,int ticket){
        if(!valid(ticket)||locked()||host==null){respond("Разблокируйте телефон для запуска видео.",ticket,false);return;}
        speech.cancel();voice.stop();videoOptions=null;
        MediaNavigation.playDetailed(this,video,intent->{if(!valid(ticket)||host==null||locked())throw new IllegalStateException();launched=true;host.launch(intent);},(display,spoken)->respond(display,spoken,ticket));
    }
    private void respond(String text,int ticket){respond(text,ticket,true);}
    private void respond(String display,String spoken,int ticket){respond(display,spoken,ticket,true,true);}
    private void finishPlanConfirmation(boolean approved){java.util.function.Consumer<Boolean> callback=pendingPlan;pendingPlan=null;recognitionEpoch++;speech.cancel();gigaAm.cancel();voice.stop();voiceEpoch++;if(host!=null)host.choices(Collections.emptyList());if(callback!=null)callback.accept(approved);}
    private void respond(String text, int ticket,boolean more){respond(text,ticket,more,true);}
    private void respond(String text, int ticket,boolean more,boolean saveHistory) { respond(text,text,ticket,more,saveHistory); }
    private void respond(String text,String spoken,int ticket,boolean more,boolean saveHistory) { if (!valid(ticket)) return; wakeResult(6);if(turnTiming!=null)turnTiming.mark(DiagnosticJournal.Event.TURN_REPLY_READY_MS); audio.requestAudioFocus(focus);answer = text; options = null; if(saveHistory)history.reply(chat, text); VoiceDiagnostics.answer(ticket, "получен"); VoiceDiagnostics.tts(ticket, "начата"); update("Отвечаю голосом…"); speak(spoken, ticket, ()->{
        if(!valid(ticket))return;
        VoiceDiagnostics.tts(ticket, "завершена");
        turns++;int waiting=ConversationMode.waitMillis(conversation,settings.getBoolean("assistant_followup",true),settings.getInt("followup_seconds",8),settings.getInt("conversation_seconds",30),turns,SystemClock.elapsedRealtime()-conversationBegan);
        if(!more||launched||waiting==0){finishRequest();return;} followup=true;heard="";listen(ticket);
    }); }
    private void speak(String text, int ticket, Runnable after) {
        if (!valid(ticket)) return;
        int utterance = ++voiceEpoch;
        if (!settings.getBoolean("assistant_spoken", true)) { main.postDelayed(() -> { if (valid(ticket)&&voiceEpoch==utterance) {voiceEpoch++;after.run();} }, 2500); return; }
        TurnTiming timing=turnTiming;
        voice.speakTimed(text, () -> main.postDelayed(() -> { if (valid(ticket) && voiceEpoch == utterance) { voiceEpoch++; after.run(); } }, 400),
            stage->{if(timing!=null&&valid(ticket)&&voiceEpoch==utterance)timing.mark(switch(stage){
                case PREPARE -> DiagnosticJournal.Event.TURN_TTS_PREPARE_MS;
                case SUBMIT -> DiagnosticJournal.Event.TURN_TTS_SUBMIT_MS;
                case SYNTHESIS -> DiagnosticJournal.Event.TURN_TTS_SYNTHESIS_MS;
                case FIRST_AUDIO -> DiagnosticJournal.Event.TURN_TTS_FIRST_AUDIO_MS;
                case PLAYING -> DiagnosticJournal.Event.TURN_TTS_PLAY_START_MS;
            });});
        main.postDelayed(() -> { if (valid(ticket) && voiceEpoch == utterance) { voiceEpoch++; voice.stop(); after.run(); } }, 60000);
    }
    private void finishRequest() {
        if(destroyed||!engaged)return;
        DiagnosticLog.event(DiagnosticJournal.Event.VOICE_END,0,activeWake);
        cycle++;recognitionEpoch++;voiceEpoch++;engaged=false;activeWake=0;firstWakeCommand=false;
        quietUntil=SystemClock.elapsedRealtime()+650;
        if(brain!=null)brain.cancel();
        if(pendingPlan!=null)finishPlanConfirmation(false);
        pendingMemoryMatches=null;appSelection.clear();conversation=false;followup=false;playerAction=false;options=null;videoOptions=null;
        dropPendingWake(4);
        speech.cancel();gigaAm.cancel();llm.cancel();cloud.cancel();remoteGateway.cancel();voice.stop();audio.abandonAudioFocusRequest(focus);
        Host previous = host; host = null; if (previous != null) previous.dismiss();
        scheduleWake(650);
    }
    @Override public void onDestroy() {
        AcousticDiagnostics acoustic = AcousticDiagnostics.current();
        if (acoustic != null) acoustic.stop("foreground_service_stopped");
        destroyed=true;cycle++;recognitionEpoch++;dropPendingWake(4);
        if(brain!=null)brain.close();if(pendingPlan!=null)finishPlanConfirmation(false); if (current == this) current = null; pendingHost = null;pendingWindowWake=0;
        Host previous = host; host = null; if (!failed && previous != null) previous.dismiss();
        main.removeCallbacksAndMessages(null); wake.close(); speech.close(); gigaAm.close(); llm.close(); cloud.close();remoteGateway.close();voice.close(); apps.close(); history.close(); audio.abandonAudioFocusRequest(focus); if (lock != null && lock.isHeld()) lock.release();
        if (!failed) lastState = "Голосовая активация выключена"; stopForeground(STOP_FOREGROUND_REMOVE); super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onTrimMemory(int level){super.onTrimMemory(level);if(level>=TRIM_MEMORY_RUNNING_LOW)SpeechRuntime.trim();}
}
