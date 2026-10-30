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
    private static final int NOTIFICATION = 77;
    interface Host { void show(String state, String heard, String answer); void choices(List<AppRegistry.App> apps); default void videos(List<YoutubeSearch.Video> videos) {} void launch(Intent intent); void dismiss(); default void confirm(String plan,java.util.function.Consumer<Boolean> reply){reply.accept(false);} }
    private static HandsFreeService current; private static Host pendingHost;
    private static String lastState = "Голосовая активация выключена";
    private final Handler main = new Handler(Looper.getMainLooper());
    private android.content.SharedPreferences settings; private WakeEngine wake; private OfflineSpeechEngine speech; private LocalVoice voice; private LocalLlm llm; private AppCatalog apps; private AssistantConversation history;
    private PowerManager.WakeLock lock; private AudioManager audio; private AudioFocusRequest focus;
    private Host host; private boolean destroyed, engaged, launched, externalMic, failed; private int cycle, voiceEpoch; private String heard = "", answer = "", chat = ""; private List<AppRegistry.App> options;
    private boolean conversation,followup,playerAction; private int turns; private long conversationBegan;
    private List<YoutubeSearch.Video> videoOptions;
    private CloudChat cloud;
    private GatewayClient remoteGateway;
    private BrainController brain;
    private java.util.function.Consumer<Boolean> pendingPlan;
    private final Runnable renewal = new Runnable() { public void run() { if (destroyed) return; if (lock != null) lock.acquire(10 * 60 * 1000L); main.postDelayed(this, 5 * 60 * 1000L); } };
    static boolean running() { return current != null && !current.destroyed; }
    static boolean answering() { return running() && current.engaged; }
    static String status() { return lastState; }
    static void request(Context context, Host host,boolean conversation) { pendingHost = host; context.startForegroundService(new Intent(context, HandsFreeService.class).setAction(SESSION).putExtra("conversation",conversation)); }
    static void detached(Host host) { if (current != null && current.host == host) { current.host = null; if (!current.launched) current.finishRequest(); } if (pendingHost == host) pendingHost = null; }
    static void choose(AppRegistry.App app) { if (current != null && current.options != null && current.options.contains(app)) current.open(app); }
    static void chooseVideo(YoutubeSearch.Video video) { if(current!=null&&current.videoOptions!=null&&current.videoOptions.contains(video))current.playVideo(video,current.cycle); }
    static void stop(Context context) { context.getSharedPreferences("wiley-mobile", MODE_PRIVATE).edit().putBoolean("handsfree_enabled", false).apply(); context.stopService(new Intent(context, HandsFreeService.class)); }
    static void pauseExternal(Runnable after) { if (current == null) { after.run(); return; } current.externalMic = true; current.wake.pause(after); }
    static void resumeExternal() { if (current != null) { current.externalMic = false; current.resumeWake(); } }
    static void reload(Context context) { if (running()) context.startForegroundService(new Intent(context, HandsFreeService.class).setAction(RELOAD)); }
    static void sessionFailed() { if (current != null) current.fail("Android не открыл помощника. Повторно выберите WileyAI в настройках цифрового помощника."); }
    @Override public void onCreate() {
        super.onCreate(); current = this; settings = getSharedPreferences("wiley-mobile", MODE_PRIVATE);
        wake = new WakeEngine(this); speech = new OfflineSpeechEngine(this); voice = new LocalVoice(this, settings, message -> update(message)); llm = new LocalLlm(this); cloud=new CloudChat(this);remoteGateway=new GatewayClient(this); history = new AssistantConversation(this);voice.ready(()->{});
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
        if (SESSION.equals(action) && pendingHost != null) { Host selected = pendingHost; pendingHost = null; begin(selected,intent.getBooleanExtra("conversation",false)); }
        else if (RELOAD.equals(action)) wake.pause(this::resumeWake);
        else if (CALL.equals(action)) { if (!WileyVoiceService.invoke()) update("Откройте раздел «Голосовой помощник» и повторите вызов"); }
        else if (settings.getBoolean("handsfree_enabled", false)) resumeWake();
        else stopSelf();
        return settings.getBoolean("handsfree_enabled", false) ? START_STICKY : START_NOT_STICKY;
    }
    private Notification notification() {
        int immutable = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT;
        PendingIntent open = PendingIntent.getActivity(this, 77, new Intent(this, MainActivity.class).setAction(SETTINGS), immutable);
        PendingIntent stop = PendingIntent.getService(this, 78, new Intent(this, HandsFreeService.class).setAction(STOP), immutable);
        PendingIntent speak = PendingIntent.getService(this, 79, new Intent(this, HandsFreeService.class).setAction(CALL), immutable);
        return new Notification.Builder(this, "voice-activation").setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Уайли · голосовой помощник").setContentText(lastState).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).setCategory(Notification.CATEGORY_SERVICE).addAction(new Notification.Action.Builder(null, "Сказать команду", speak).build()).addAction(new Notification.Action.Builder(null, "Остановить", stop).build()).build();
    }
    private void update(String state) { lastState = state; if (!destroyed) { Host visible = host == null ? pendingHost : host; if (visible != null) visible.show(state, heard, answer); ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION, notification()); } }
    private void fail(String state) { failed = true; update(state); settings.edit().putBoolean("handsfree_enabled", false).apply(); stopSelf(); }
    private void resumeWake() {
        if (destroyed || engaged || externalMic || wake.busy()) return;
        if (!settings.getBoolean("handsfree_enabled", false)) { stopSelf(); return; }
        if (!WileyVoiceService.selected(this)) { settings.edit().putBoolean("handsfree_enabled", false).apply(); stopSelf(); return; }
        try {
            Path model = VerifiedModelInstaller.active(getFilesDir().toPath().resolve("speech-models")); if (model == null) throw new IllegalStateException();
            String phrase = settings.getString("wake_phrase", WakePhrase.DEFAULT); if (!WakePhrase.valid(phrase)) phrase = WakePhrase.DEFAULT;
            String selected = WakePhrase.label(phrase); update("Загружаю голосовую активацию…");
            wake.start(model, phrase, () -> update("Скажите «" + selected + "»"), dialogue -> {
                if (destroyed || !settings.getBoolean("handsfree_enabled", false)) return; update("Вызываю Уайли…");
                if (!WileyVoiceService.invoke(dialogue)) { fail("Служба Android отключена. Повторно выберите WileyAI в настройках цифрового помощника."); }
            }, message -> { fail(message); });
        } catch (Exception problem) { fail("Установите русский комплект Vosk в «Компонентах»"); }
    }
    private void begin(Host selected,boolean dialogue) {
        if (externalMic) { selected.show("Микрофон занят другим распознавателем. Повторите вызов позже.", "", ""); return; }
        if (engaged) { host = selected; host.show(lastState, heard, answer); if (options != null) host.choices(options); return; }
        cycle++; int ticket = cycle; speech.cancel(); llm.cancel(); cloud.cancel();remoteGateway.cancel(); voice.stop(); engaged = true; launched = false; host = selected; options = null; videoOptions=null; chat = ""; heard = ""; answer = "";
        conversation=dialogue; followup=false; turns=0;conversationBegan=SystemClock.elapsedRealtime();
        update("Готовлю микрофон…"); audio.requestAudioFocus(focus);
        wake.pause(() -> { if (valid(ticket)) { if(dialogue)process("давай поговорим",ticket);else listen(ticket); } });
    }
    private boolean valid(int ticket) { return !destroyed && engaged && cycle == ticket; }
    private void listen(int ticket) {
        if (!valid(ticket)) return;
        if (speech.busy()) { main.postDelayed(() -> listen(ticket), 100); return; }
        try {
            Path model = VerifiedModelInstaller.active(getFilesDir().toPath().resolve("speech-models")); if (model == null) throw new IllegalStateException();
            int waiting=followup?ConversationMode.waitMillis(conversation,true,settings.getInt("followup_seconds",8),settings.getInt("conversation_seconds",30),turns,SystemClock.elapsedRealtime()-conversationBegan):15000;
            if(waiting==0){finishRequest();return;}
            speech.start(model, new OfflineSpeechEngine.Listener() {
                public void ready(Runnable startMicrophone) {
                    if (!valid(ticket)) return;
                    if (!settings.getBoolean("assistant_listening_prompt", true)) { startMicrophone.run(); return; }
                    update("Распознаватель готов…");
                    java.util.concurrent.atomic.AtomicBoolean once = new java.util.concurrent.atomic.AtomicBoolean();
                    Runnable begin = () -> { if (valid(ticket) && once.compareAndSet(false, true)) { voice.stop(); main.postDelayed(startMicrophone, 160); } };
                    voice.speakCompleted("Слушаю", begin); main.postDelayed(begin, 5000);
                }
                public void state(String text) { if (valid(ticket)) { update(text.startsWith("Слушаю") ? followup?"Слушаю следующий вопрос · "+waiting/1000+" сек.":"Слушаю команду…" : text); if (text.startsWith("Слушаю")) { ToneGenerator signal = new ToneGenerator(AudioManager.STREAM_MUSIC, 35); signal.startTone(ToneGenerator.TONE_PROP_BEEP, 110); main.postDelayed(signal::release, 200); } } }
                public void partial(String text) { if (valid(ticket)) { heard = text; update("Слушаю…"); } }
                public void result(String text) { if (!valid(ticket)) return; if (text.isEmpty()) { finishRequest(); return; } heard = text; followup=false;update("Поняла: «" + text + "»"); if(videoOptions!=null){int choice=option(text);if(text.matches("да|да включи|включи|включай|включи первое|первое|первое видео"))choice=0;if(choice>=0&&choice<videoOptions.size())playVideo(videoOptions.get(choice),ticket);else if(text.matches("нет|отмена|не включай|закончили")){videoOptions=null;respond("Хорошо, видео не включаю.",ticket,false);}else{videoOptions=null;process(text,ticket);}return;} if (options != null) { int choice = option(text); if (choice >= 0 && choice < options.size()) open(options.get(choice)); else respond("Скажите номер варианта или выберите приложение на экране.", ticket); } else process(text, ticket); }
                public void error(String text) { if (valid(ticket)) respond(text, ticket,false); }
                public void finished() {}
            },waiting);
        } catch (Exception missing) { respond("Сначала установите русский комплект Vosk в приложении.", ticket,false); }
    }
    static int option(String text) { String value = text.toLowerCase(Locale.ROOT).trim(); String[] names = {"первый", "второй", "третий", "четвертый", "пятый"}; for (int i = 0; i < names.length; i++) if (value.replace('ё','е').matches("(?:вариант )?(?:" + names[i] + "|" + (i + 1) + ")")) return i; return -1; }
    private boolean locked() { return ((KeyguardManager)getSystemService(KEYGUARD_SERVICE)).isDeviceLocked(); }
    private void process(String text, int ticket) {
        if(pendingPlan!=null){String choice=text.toLowerCase(Locale.ROOT).trim();if(choice.matches("да|выполни|выполняй|подтверждаю|согласен|хорошо")){finishPlanConfirmation(true);return;}if(choice.matches("нет|отмена|отмени|стоп|закончили")){finishPlanConfirmation(false);return;}finishPlanConfirmation(false);return;}
        history.submit(text, (id, context) -> {
            if (!valid(ticket)) return; chat = id; dispatch(text,ticket,context);
        }, error -> {
            if (!valid(ticket)) return; chat = "";
            if (PhoneCommands.parse(text,true) != null || ConversationMode.parse(text) != 0) dispatch(text,ticket,Collections.emptyList());
            else respond(error,ticket,false);
        });
    }
    private void dispatch(String text,int ticket,List<LocalChatRepository.Message> context) {
            if (!valid(ticket)) return; PhoneCommands.Action action = StructuredActionAdapter.requiresPlan(text)?null:PhoneCommands.parse(text, true);
            int mode=ConversationMode.parse(text);
            if(mode==ConversationMode.START){conversation=true;respond("Давай поговорим. Скажи, что тебя интересует. Чтобы закончить, скажи «закончили».",ticket);return;}
            if(mode==ConversationMode.END){conversation=false;respond("Хорошо, закончили. Позови меня, когда понадоблюсь.",ticket,false);return;}
            if (action != null) {
                if (action.kind.equals("open")) { if (locked()) { respond("Разблокируйте телефон для открытия приложения.", ticket); return; } openTarget(action.value, ticket); }
                else if(action.kind.equals("media_search")||action.kind.equals("media_play_search")){
                    if(locked()||host==null){respond("Разблокируйте телефон для поиска музыки и видео.",ticket);return;}
                    update("Ищу музыку или видео…");
                    MediaNavigation.execute(this,action,intent->{if(!valid(ticket)||host==null||locked())throw new IllegalStateException();launched=true;host.launch(intent);},reply->respond(reply,ticket),videos->{
                        if(!valid(ticket)||host==null)return;videoOptions=videos;host.videos(videos);
                        answer="1. "+videos.get(0).title()+"\n"+videos.get(0).channel();update("Включить найденное видео?");
                        speak("Нашла: "+videos.get(0).title()+". Включить? Скажи «да», номер другого варианта или «отмена».",ticket,()->listen(ticket));
                    });
                }
                else { playerAction=action.kind.equals("media")&&action.value.matches("play|next|previous");PhoneActionCore.execute(this, action, reply -> {playerAction=false;respond(reply, ticket);}); }
            } else if (locked()) respond("Разблокируйте телефон для разговора с моделью. Время, музыка и громкость доступны сразу.", ticket);
            else if (text.toLowerCase(Locale.ROOT).matches(".*на (?:пк|компьютере)[.! ]*$")) respond("Сейчас я управляю телефоном. Режим компьютера доступен в приложении.", ticket);
            else {
                try {
                    ModelManager manager=new ModelManager(this);
                    if(manager.toolsAllowed()||manager.selected()==BrainProvider.Kind.ACCOUNT_OAUTH){
                        Host surface=host;brain.generate(context,new BrainController.Host(){
                            public boolean active(){return valid(ticket);}
                            public void state(String value){if(valid(ticket)){if(value.startsWith("Выполняю:"))playerAction=true;update(value);}}
                            public void confirm(String plan,java.util.function.Consumer<Boolean> reply){if(!valid(ticket)||surface==null){reply.accept(false);return;}pendingPlan=reply;surface.confirm(plan,HandsFreeService.this::finishPlanConfirmation);answer=plan;update("Подтвердите план: «да» или «отмена»");speak(plan+". Выполнить? Скажите да или отмена.",ticket,()->listen(ticket));}
                            public void launch(Intent intent){if(!valid(ticket)||surface==null||locked())throw new IllegalStateException();launched=true;surface.launch(intent);}
                            public void done(String value){playerAction=false;if(valid(ticket))respond(value,ticket);}
                            public void error(String value){playerAction=false;if(valid(ticket))respond(value,ticket);}
                            public void finished(){}
                        });return;
                    }
                    boolean gateway=GatewayClient.enabled(this),remote=CloudChat.enabled(this);Path model = gateway||remote?null:LlmModels.readActive(getFilesDir().toPath().resolve("llm-models")); if (!gateway&&!remote&&model == null) { respond("Установите разговорную модель или подключите облачный чат в разделе «Компоненты». Команды телефону уже доступны.", ticket); return; }
                    update(gateway?"Отвечаю через WileyAI Gateway…":remote?"Отвечаю через выбранный облачный сервис…":"Отвечаю на телефоне…");
                    LocalLlm.Listener listener = new LocalLlm.Listener() {
                        public void state(String text) { if (valid(ticket)) update(text); }
                        public void partial(String text) { if (valid(ticket)) { answer = text; update("Отвечаю…"); } }
                        public void done(String text, boolean stopped) { if (valid(ticket)) respond(text.isEmpty() ? "Не удалось получить ответ. Повторите вопрос." : text, ticket,true,!(gateway&&remoteGateway.savedResponse())); }
                        public void error(String text) { if (valid(ticket)) respond(text, ticket); } public void finished() {}
                    };
                    if(gateway)remoteGateway.generate(chat,context,listener);else if(remote)cloud.generate(context,listener);else llm.generate(model,LocalLlm.prompt(context),listener);
                } catch (Exception missing) { respond("Не удалось открыть разговорную модель. Проверьте её в приложении.", ticket); }
            }
    }
    private void openTarget(String target, int ticket) {
        apps.resolve(target, matches -> {
            if (!valid(ticket)) return;
            if (matches.size() == 1) { open(matches.get(0)); return; }
            if (matches.size() > 1) { options = new ArrayList<>(matches.subList(0, Math.min(5, matches.size()))); if (host != null) host.choices(options); StringBuilder prompt = new StringBuilder("Какое приложение? "); for (int i = 0; i < options.size(); i++) prompt.append(i+1).append(": ").append(options.get(i).label()).append(". "); prompt.append("Скажите номер."); speak(prompt.toString(), ticket, () -> listen(ticket)); return; }
            String url = target.matches("(?i)^https?://[^\\s]+$") ? target : "";
            if (url.isEmpty()) {
                List<AppRegistry.App> suggestions=AppRegistry.suggest(apps.entries(),target);
                if(!suggestions.isEmpty()){
                    options=new ArrayList<>(suggestions);if(host!=null)host.choices(options);
                    StringBuilder prompt=new StringBuilder("Есть похожие названия. ");for(int i=0;i<options.size();i++)prompt.append(i+1).append(": ").append(options.get(i).label()).append(". ");prompt.append("Скажите номер или выберите на экране.");
                    speak(prompt.toString(),ticket,()->listen(ticket));return;
                }
                respond("Приложение не найдено. Скажите его название иначе или добавьте название в «Команды → Мои приложения».", ticket); return;
            }
            try { Uri uri = Uri.parse(url); if (uri.getHost() == null || uri.getUserInfo() != null || locked() || host == null) throw new IllegalStateException(); launched = true; host.launch(new Intent(Intent.ACTION_VIEW, uri)); respond("Открываю сайт на телефоне.", ticket); } catch (Exception failed) { launched = false; respond("Не удалось открыть сайт. Проверьте адрес и разблокируйте телефон.", ticket); }
        });
    }
    private void open(AppRegistry.App app) {
        int ticket = cycle; if (!valid(ticket)) return;
        if (locked() || host == null) { respond("Разблокируйте телефон и повторите команду открытия.", ticket); return; }
        try {
            ComponentName component = new ComponentName(app.packageName(), app.activity()); ActivityInfo actual = getPackageManager().getActivityInfo(component, 0);
            if (!actual.enabled || !actual.exported || !actual.applicationInfo.enabled) throw new IllegalStateException();
            Intent intent = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setComponent(component).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            launched = true; host.launch(intent); respond("Открываю «" + app.label() + "» на телефоне.", ticket);
        } catch (Exception failed) { launched = false; respond("Не удалось открыть приложение. Проверьте его доступность.", ticket); }
    }
    private void playVideo(YoutubeSearch.Video video,int ticket){
        if(!valid(ticket)||locked()||host==null){respond("Разблокируйте телефон для запуска видео.",ticket,false);return;}
        speech.cancel();voice.stop();videoOptions=null;
        MediaNavigation.play(this,video,intent->{if(!valid(ticket)||host==null||locked())throw new IllegalStateException();launched=true;host.launch(intent);},text->respond(text,ticket));
    }
    private void respond(String text,int ticket){respond(text,ticket,true);}
    private void finishPlanConfirmation(boolean approved){java.util.function.Consumer<Boolean> callback=pendingPlan;pendingPlan=null;speech.cancel();voice.stop();voiceEpoch++;if(host!=null)host.choices(Collections.emptyList());if(callback!=null)callback.accept(approved);}
    private void respond(String text, int ticket,boolean more){respond(text,ticket,more,true);}
    private void respond(String text, int ticket,boolean more,boolean saveHistory) { if (!valid(ticket)) return; audio.requestAudioFocus(focus);answer = text; options = null; if(saveHistory)history.reply(chat, text); update("Отвечаю голосом…"); speak(text, ticket, ()->{
        if(!valid(ticket))return;
        turns++;int waiting=ConversationMode.waitMillis(conversation,settings.getBoolean("assistant_followup",true),settings.getInt("followup_seconds",8),settings.getInt("conversation_seconds",30),turns,SystemClock.elapsedRealtime()-conversationBegan);
        if(!more||launched||waiting==0){finishRequest();return;} followup=true;heard="";listen(ticket);
    }); }
    private void speak(String text, int ticket, Runnable after) {
        if (!valid(ticket)) return;
        int utterance = ++voiceEpoch;
        if (!settings.getBoolean("assistant_spoken", true)) { main.postDelayed(() -> { if (valid(ticket)) after.run(); }, 2500); return; }
        voice.speakCompleted(text, () -> main.postDelayed(() -> { if (valid(ticket) && voiceEpoch == utterance) { voiceEpoch++; after.run(); } }, 400));
        main.postDelayed(() -> { if (valid(ticket) && voiceEpoch == utterance) { voiceEpoch++; voice.stop(); after.run(); } }, 60000);
    }
    private void finishRequest() {
        if(brain!=null)brain.cancel();if(pendingPlan!=null)finishPlanConfirmation(false);
        if (destroyed) return; cycle++; voiceEpoch++; engaged = false; conversation=false;followup=false;playerAction=false;options = null;videoOptions=null; speech.cancel(); llm.cancel(); cloud.cancel();remoteGateway.cancel();voice.stop(); audio.abandonAudioFocusRequest(focus);
        Host previous = host; host = null; if (previous != null) previous.dismiss();
        main.postDelayed(this::resumeWake, 650);
    }
    @Override public void onDestroy() {
        if(brain!=null)brain.close();if(pendingPlan!=null)finishPlanConfirmation(false);
        destroyed = true; cycle++; if (current == this) current = null; pendingHost = null;
        Host previous = host; host = null; if (!failed && previous != null) previous.dismiss();
        main.removeCallbacksAndMessages(null); wake.close(); speech.close(); llm.close(); cloud.close();remoteGateway.close();voice.close(); apps.close(); history.close(); audio.abandonAudioFocusRequest(focus); if (lock != null && lock.isHeld()) lock.release();
        if (!failed) lastState = "Голосовая активация выключена"; stopForeground(STOP_FOREGROUND_REMOVE); super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onTrimMemory(int level){super.onTrimMemory(level);if(level>=TRIM_MEMORY_RUNNING_LOW)SpeechRuntime.trim();}
}
