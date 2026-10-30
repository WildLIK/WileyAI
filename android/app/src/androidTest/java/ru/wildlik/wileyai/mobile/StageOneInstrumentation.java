package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteException;
import android.text.Spanned;
import android.text.style.TypefaceSpan;

/** SDK-only device tests; deliberately needs no downloaded AndroidX test runner. */
public final class StageOneInstrumentation extends Instrumentation {
    private static final String DATABASE = "stage-one-instrumentation.db";
    private int current;
    private boolean speechProbe;
    private boolean iteration;
    private boolean setupApps;
    private boolean llmProbe;
    private boolean setupVoice, assistantProbe, googleVoice, loopback, wakeVocabulary, mediaProbe, routingProbe;
    private String only = "";
    private interface Test { void run() throws Exception; }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); only = arguments == null ? "" : arguments.getString("only", ""); speechProbe = arguments != null && "true".equals(arguments.getString("speech")); iteration = arguments != null && "true".equals(arguments.getString("iteration")); setupApps = arguments != null && "true".equals(arguments.getString("setup_apps")); llmProbe = arguments != null && "true".equals(arguments.getString("llm")); setupVoice = arguments != null && "true".equals(arguments.getString("setup_voice")); assistantProbe = arguments != null && "true".equals(arguments.getString("assistant")); googleVoice = arguments != null && "true".equals(arguments.getString("google_voice")); loopback = arguments != null && "true".equals(arguments.getString("loopback")); wakeVocabulary = arguments != null && "true".equals(arguments.getString("wake_vocab")); mediaProbe = arguments != null && "true".equals(arguments.getString("media")); routingProbe = arguments != null && "true".equals(arguments.getString("routing")); start(); }
    private void test(String name, Test test) throws Exception {
        if (!only.isEmpty() && !name.equals(only)) return;
        Bundle status = new Bundle(); status.putString("class", getClass().getName()); status.putString("test", name);
        status.putString("id", "WileyAI"); status.putInt("numtests", only.isEmpty() ? 14 + (speechProbe ? 1 : 0) + (iteration ? 1 : 0) + (setupApps ? 1 : 0) + (llmProbe ? 2 : 0) + (assistantProbe ? 7 : 0) + (googleVoice ? 1 : 0) + (loopback ? 1 : 0) + (mediaProbe ? 6 : 0) + (wakeVocabulary ? 3 : 0) + (routingProbe ? 1 : 0) : 1); status.putInt("current", ++current); sendStatus(1, status);
        try { test.run(); sendStatus(0, status); }
        catch (Throwable failure) { status.putString("stack", android.util.Log.getStackTraceString(failure)); sendStatus(-2, status); throw failure; }
    }
    private void onMain(Runnable work) {
        java.util.concurrent.atomic.AtomicReference<Throwable> failure = new java.util.concurrent.atomic.AtomicReference<>();
        super.runOnMainSync(() -> { try { work.run(); } catch (Throwable error) { failure.set(error); } });
        if (failure.get() != null) throw new AssertionError("Ошибка проверки на UI-потоке", failure.get());
    }
    private static void check(boolean value) { if (!value) throw new AssertionError("Проверка не прошла"); }
    private static boolean hasText(android.view.View view, String text) {
        if (view instanceof android.widget.TextView && ((android.widget.TextView)view).getText().toString().equals(text)) return true;
        if (view instanceof android.view.ViewGroup) {
            android.view.ViewGroup group = (android.view.ViewGroup)view;
            for (int i = 0; i < group.getChildCount(); i++) if (hasText(group.getChildAt(i), text)) return true;
        }
        return false;
    }
    private static android.view.View find(android.view.View view, String text) {
        if (text.contentEquals(view.getContentDescription() == null ? "" : view.getContentDescription())) return view;
        if (view instanceof android.widget.TextView && ((android.widget.TextView)view).getText().toString().equals(text)) return view;
        if (view instanceof android.view.ViewGroup) {
            android.view.ViewGroup group = (android.view.ViewGroup)view;
            for (int i = 0; i < group.getChildCount(); i++) { android.view.View found = find(group.getChildAt(i), text); if (found != null) return found; }
        }
        return null;
    }
    private static void click(Activity activity, String text) {
        android.view.View control = find(activity.getWindow().getDecorView(), text); check(control != null);
        while (!control.isClickable() && control.getParent() instanceof android.view.View) control = (android.view.View)control.getParent();
        check(control.isClickable()); control.performClick();
    }
    @Override public void onStart() {
        Context context = getTargetContext(); Bundle result = new Bundle();
        try {
            if(only.equals("phoneFinishChecks"))test("phoneFinishChecks",()->result.putString("phone_final_checks",GatewayDeviceProbe.finalChecks(this,context)));
            if(only.equals("brainPlans"))test("brainPlans",()->result.putString("brain_plans",BrainProbe.plans(this,context)));
            if(only.equals("brainLoop"))test("brainLoop",()->result.putString("brain_loop",BrainProbe.loop(this,context)));
            if(only.equals("brainNative"))test("brainNative",()->result.putString("brain_native",BrainProbe.nativeFixture(this,context)));
            if(only.equals("brainConversation"))test("brainConversation",()->result.putString("brain_conversation",BrainProbe.conversation(this,context)));
            if(only.equals("gatewayDevice"))test("gatewayDevice",()->{
                try(java.io.InputStream input=getContext().getAssets().open("gateway-fixture.json")){
                    java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();byte[] buffer=new byte[4096];int count;while((count=input.read(buffer))!=-1)bytes.write(buffer,0,count);
                    result.putString("gateway_device",GatewayDeviceProbe.run(this,context,new org.json.JSONObject(bytes.toString("UTF-8"))));
                }
            });
            if (setupVoice) { check(context.getPackageManager().getApplicationInfo("com.k2fsa.sherpa.onnx.tts.engine", 0).enabled); check(context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE).edit().putString("offline_engine", "com.k2fsa.sherpa.onnx.tts.engine").remove("offline_voice").putString("voice_engine_description:com.k2fsa.sherpa.onnx.tts.engine", "Piper · Irina · нейронная озвучка без сети").commit()); }
            test("historySurvivesReopen", () -> {
                context.deleteDatabase(DATABASE); String id;
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) {
                    id = repository.submit("", "Привет без интернета"); repository.append(id, "assistant", "Нет подключённой LLM"); repository.draft(id, "Черновик");
                }
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) {
                    check(repository.chats().size() == 1); check(repository.messages(id).size() == 2); check(repository.chat(id).draft().equals("Черновик"));
                    check(repository.messages(id).get(0).content().equals("Привет без интернета"));
                }
            });
            test("renameDeleteAndIsolation", () -> {
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) {
                    String first = repository.chats().get(0).id(), second = repository.submit("", "Другой чат");
                    repository.rename(first, "Новое название"); check(repository.chat(first).title().equals("Новое название"));
                    repository.delete(first); check(repository.messages(first).isEmpty()); check(repository.messages(second).size() == 1);
                }
            });
            test("foreignKeyFailurePreservesHistory", () -> {
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) {
                    String id = repository.chats().get(0).id(); int before = repository.messages(id).size(); boolean failed = false;
                    try { repository.append("missing-chat", "user", "orphan"); } catch (SQLiteException expected) { failed = true; }
                    check(failed); check(repository.messages(id).size() == before);
                    boolean invalid = false; try { repository.append(id, "invalid-role", "bad"); } catch (SQLiteException expected) { invalid = true; }
                    check(invalid); check(repository.messages(id).size() == before);
                }
            });
            test("unknownVersionDoesNotDeleteData", () -> {
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) { repository.getWritableDatabase().setVersion(3); }
                boolean rejected = false;
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) { repository.chats(); } catch (SQLiteException expected) { rejected = true; }
                check(rejected);
                try (SQLiteDatabase db = SQLiteDatabase.openDatabase(context.getDatabasePath(DATABASE).getPath(), null, SQLiteDatabase.OPEN_READWRITE)) { db.setVersion(2); }
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) { check(repository.chats().size() == 1); }
            });
            test("pairingValidationAndPrivateAddresses", () -> {
                check(SettingsRepository.privateIp("100.64.0.1")); check(!SettingsRepository.privateIp("8.8.8.8"));
                String link = "wileyai://pair?host=192.168.1.2&port=48443&fingerprint=" + new String(new char[64]).replace('\0', 'a') + "&code=abcdefghijklmnopqrstuvwx";
                check(SettingsRepository.parsePair(link).getJSONArray("hosts").length() == 1);
                boolean rejected = false; try { SettingsRepository.parsePair(link.replace("192.168.1.2", "8.8.8.8")); } catch (Exception expected) { rejected = true; }
                check(rejected);
            });
            test("legacyEncryptedConnectionRoundTrip", () -> {
                Context isolated = new android.content.ContextWrapper(context) {
                    @Override public android.content.SharedPreferences getSharedPreferences(String name, int mode) {
                        return context.getSharedPreferences("stage-one-settings-test", mode);
                    }
                };
                SettingsRepository settings = new SettingsRepository(isolated);
                try {
                    String token = "test_token_abcdefghijklmnopqrstuvwxyz1234";
                    org.json.JSONObject profile = new org.json.JSONObject().put("hosts", new org.json.JSONArray().put("192.168.1.2")).put("port", 48443)
                        .put("fingerprint", new String(new char[64]).replace('\0', 'a')).put("token", token);
                    settings.saveProfile(profile);
                    check(!settings.preferences.getString("connection", "").contains(token));
                    check(new SettingsRepository(isolated).readProfile().getString("token").equals(token));
                } finally { settings.preferences.edit().clear().commit(); }
            });
            test("boundedHistoryKeepsChronologicalOrder", () -> {
                try (LocalChatRepository repository = new LocalChatRepository(context, DATABASE)) {
                    String id = repository.submit("", "первое"); repository.append(id, "assistant", "второе"); repository.append(id, "user", "третье");
                    check(repository.messages(id, 2).size() == 2); check(repository.messages(id, 2).get(0).content().equals("второе"));
                    check(repository.messages(id).size() == 3); repository.delete(id);
                }
            });
            test("markdownPreservesCodeAndText", () -> {
                CharSequence value = MessageRenderer.format("# Заголовок\n**Жирно** и `код`\n```java\nif (a < b) {}\n```");
                check(value.toString().contains("if (a < b) {}")); check(!value.toString().contains("```"));
                check(((Spanned)value).getSpans(0, value.length(), TypefaceSpan.class).length == 2);
            });
            test("mainScreenStartsWithoutPairingGate", () -> {
                Activity activity = startActivitySync(new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                onMain(() -> {
                    check(hasText(activity.getWindow().getDecorView(), "Телефон · без разговорной модели  ▾") || hasText(activity.getWindow().getDecorView(), "Телефон · Qwen3 0.6B  ▾"));
                    check(hasText(activity.getWindow().getDecorView(), "Чаты"));
                    check(!hasText(activity.getWindow().getDecorView(), "Подключить")); activity.finish();
                });
            });
            test("dialogsFollowAllFourPalettes", () -> {
                Activity activity = startActivitySync(new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                try {
                    for (String theme : new String[]{"aurora", "ice", "ember", "nebula"}) {
                        MobileUi ui = new MobileUi(activity, theme); android.app.AlertDialog[] shown = new android.app.AlertDialog[1];
                        onMain(() -> shown[0] = ui.dialog().setTitle("Где обрабатывать сообщения?").setItems(new String[]{"На телефоне · команды и локальная история"}, (d, w) -> {}).setNegativeButton("Отмена", null).show());
                        waitForIdleSync(); // OnShow styling runs through the Android message queue.
                        onMain(() -> {
                            android.app.AlertDialog dialog = shown[0];
                            check(dialog.getWindow().getAttributes().dimAmount < .5f);
                            android.content.res.TypedArray colors = dialog.getContext().obtainStyledAttributes(new int[]{android.R.attr.textColorPrimary});
                            check(colors.getColor(0, 0) == ui.theme.text); colors.recycle();
                            android.graphics.drawable.GradientDrawable background = (android.graphics.drawable.GradientDrawable)dialog.getWindow().getDecorView().getBackground();
                            check(background.getCornerRadius() > 0);
                            android.widget.TextView row = (android.widget.TextView)dialog.getListView().getAdapter().getView(0, null, dialog.getListView());
                            check(row.getCurrentTextColor() == ui.theme.text); check(row.getMaxLines() > 1);
                            check(dialog.getButton(android.content.DialogInterface.BUTTON_NEGATIVE).getCurrentTextColor() == ui.theme.accentText);
                            dialog.dismiss();
                        });
                    }
                } finally { onMain(activity::finish); }
            });
            test("voskNativeLibraryLoadsForDeviceAbi", () -> org.vosk.LibVosk.setLogLevel(org.vosk.LogLevel.WARNINGS));
            test("componentNavigationAndInlineCommand", () -> {
                Activity activity = startActivitySync(new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                onMain(() -> {
                    click(activity, "Компоненты");
                    for (String text : new String[]{"Распознавание речи", "Озвучка ответов", "Команды телефона", "Облачные чаты", "Использование ПК"}) check(hasText(activity.getWindow().getDecorView(), text));
                    click(activity, "Распознавание речи"); check(hasText(activity.getWindow().getDecorView(), "Скачивать только по Wi-Fi"));
                    click(activity, "Назад"); click(activity, "Команды телефона"); click(activity, "Текущая громкость");
                    android.media.AudioManager audio = (android.media.AudioManager)context.getSystemService(Context.AUDIO_SERVICE);
                    int maximum = audio.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC), actual = audio.getStreamVolume(android.media.AudioManager.STREAM_MUSIC);
                    String percentage=(maximum == 0 ? 0 : Math.round(actual * 100f / maximum))+"%";
                    String expected=android.os.Build.MANUFACTURER.equalsIgnoreCase("samsung")&&maximum==15?"Громкость музыки на телефоне: около "+actual*10+" из 150 по шкале Samsung ("+percentage+" максимума).":"Громкость музыки на телефоне: "+percentage+".";
                    check(hasText(activity.getWindow().getDecorView(),expected));
                    check(hasText(activity.getWindow().getDecorView(), "Выполнить команду"));check(!hasText(activity.getWindow().getDecorView(),"Приложения и названия для голоса"));
                    click(activity,"Мои приложения");check(hasText(activity.getWindow().getDecorView(),"Приложения и названия для голоса"));activity.finish();
                });
            });
            test("offlineVoicesExposeActualEngineMetadata", () -> {
                android.content.SharedPreferences preferences = context.getSharedPreferences("stage-one-voices-test", Context.MODE_PRIVATE);
                LocalVoice[] voice = new LocalVoice[1]; java.util.concurrent.CountDownLatch initialized = new java.util.concurrent.CountDownLatch(1);
                java.util.concurrent.atomic.AtomicReference<String> failure = new java.util.concurrent.atomic.AtomicReference<>();
                try {
                    onMain(() -> { voice[0] = new LocalVoice(context, preferences, message -> { failure.set(message); initialized.countDown(); }); voice[0].ready(initialized::countDown); });
                    check(initialized.await(20, java.util.concurrent.TimeUnit.SECONDS)); check(failure.get() == null);
                    onMain(() -> {
                        check(!voice[0].engineLabel().isEmpty());
                        for (android.speech.tts.Voice item : voice[0].voices()) { check(!item.isNetworkConnectionRequired()); check(item.getLocale().getLanguage().equals("ru")); check(!VoiceLabels.quality(item.getQuality()).isEmpty()); }
                    });
                } finally { if (voice[0] != null) onMain(() -> voice[0].close()); preferences.edit().clear().commit(); }
            });
            test("launcherScanAndAliasesSurviveRestart", () -> {
                android.content.SharedPreferences preferences = context.getSharedPreferences("stage-one-apps-test", Context.MODE_PRIVATE);
                AppCatalog[] catalog = new AppCatalog[1];
                try {
                    java.util.concurrent.CountDownLatch scanned = new java.util.concurrent.CountDownLatch(1);
                    onMain(() -> catalog[0] = new AppCatalog(context, preferences, () -> { if (!catalog[0].scanning()) scanned.countDown(); }));
                    check(scanned.await(10, java.util.concurrent.TimeUnit.SECONDS));
                    AppRegistry.App target = null;
                    for (AppRegistry.App app : catalog[0].entries()) { check(!app.label().isEmpty()); if (app.packageName().equals(context.getPackageName())) target = app; }
                    check(target != null); String id = target.id();
                    java.util.concurrent.CountDownLatch saved = new java.util.concurrent.CountDownLatch(1);
                    AppRegistry.App selected = target;
                    catalog[0].saveAliases(selected, java.util.Arrays.asList("тестовый помощник"), success -> { check(success); saved.countDown(); });
                    check(saved.await(5, java.util.concurrent.TimeUnit.SECONDS));
                    onMain(() -> catalog[0].close());
                    java.util.concurrent.CountDownLatch rescanned = new java.util.concurrent.CountDownLatch(1);
                    onMain(() -> catalog[0] = new AppCatalog(context, preferences, () -> { if (!catalog[0].scanning()) rescanned.countDown(); }));
                    check(rescanned.await(10, java.util.concurrent.TimeUnit.SECONDS));
                    boolean found = false;
                    for (AppRegistry.App app : AppRegistry.resolve(catalog[0].entries(), "тестовый помощник")) if (app.id().equals(id)) found = true;
                    check(found);
                } finally { if (catalog[0] != null) onMain(() -> catalog[0].close()); preferences.edit().clear().commit(); }
            });
            if (assistantProbe) { test("assistantTemporalClock", () -> AssistantProbe.temporalClock(this, context)); test("assistantMetadata", () -> AssistantProbe.metadata(context)); test("assistantHistoryIsolation", () -> AssistantProbe.history(this, context)); }
            if (assistantProbe) {
                test("deletedAssistantHistoryRecovery",()->{Bundle extra=new Bundle();extra.putString("history_recovery",IterationNineProbe.history(this,context));sendStatus(0,extra);});
                test("speechModelReuse",()->{Bundle extra=new Bundle();extra.putString("model_reuse",IterationNineProbe.cache(context));sendStatus(0,extra);});
                test("youtubeAndCloudParsing",IterationNineProbe::parsers);
                test("cloudConsentStorageAndTransport",()->IterationNineProbe.cloudTransport(this,context));
            }
            if (only.equals("publicYoutubeSearch")) test("publicYoutubeSearch",()->{Bundle extra=new Bundle();extra.putString("public_youtube",IterationNineProbe.publicYoutube(context));sendStatus(0,extra);});
            if (googleVoice) test("googleVoiceCompleted", () -> result.putString("voice_probe", AssistantProbe.googleVoice(this, context)));
            if (routingProbe) test("assistantTemporalRouting", () -> { Bundle extra=new Bundle();extra.putString("temporal_routing",AssistantProbe.temporalRouting(context));sendStatus(0,extra); });
            if (mediaProbe) { test("mediaPermissionMetadata", () -> MediaProbe.permissionMetadata(context)); test("mediaColdStart", () -> MediaProbe.cold(this, context)); test("mediaTransportAndSeek", () -> MediaProbe.transport(this, context)); test("mediaUnsupportedAndUnconfirmed", () -> MediaProbe.failure(this, context)); test("mediaSearchIntents", () -> MediaProbe.intents(this, context)); test("conversationWakePhrase", () -> { Bundle extra=new Bundle();extra.putString("conversation_wake",SyntheticSpeechProbe.conversation(this,context));sendStatus(0,extra); }); }
            if (wakeVocabulary) { test("shortWakePhrase", () -> { Bundle extra = new Bundle(); extra.putString("wake", SyntheticSpeechProbe.wake(this, context, false)); sendStatus(0, extra); }); test("shortWakeRejectsOkayAlone", () -> { Bundle extra = new Bundle(); extra.putString("wake_negative", SyntheticSpeechProbe.wake(this, context, true)); sendStatus(0, extra); }); }
            if (wakeVocabulary) test("wakeVocabulary", () -> { Bundle extra = new Bundle(); extra.putString("vocabulary", AssistantProbe.vocabulary(context)); sendStatus(0, extra); });
            if (loopback) test("physicalBackgroundWakeCycle", () -> result.putString("assistant_loopback", AssistantLoopbackProbe.run(this, context)));
            if (speechProbe) test("syntheticOfflineVoiceToInstalledVosk", () -> result.putString("speech_probe", SyntheticSpeechProbe.run(this, context)));
            if (iteration) test("musicVolumeActuallyChangesAndRestores", () -> {
                check(context.checkSelfPermission(android.Manifest.permission.MODIFY_AUDIO_SETTINGS) == android.content.pm.PackageManager.PERMISSION_GRANTED);
                Activity activity = startActivitySync(new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                android.media.AudioManager audio = (android.media.AudioManager)context.getSystemService(Context.AUDIO_SERVICE);
                int before = audio.getStreamVolume(android.media.AudioManager.STREAM_MUSIC), maximum = audio.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC);
                java.util.concurrent.atomic.AtomicReference<String> reply = new java.util.concurrent.atomic.AtomicReference<>();
                try {
                    onMain(() -> new PhoneActionEngine(activity, reply::set, null, () -> true).execute(PhoneCommands.parse(before == 0 ? "прибавить громкость" : "убавить громкость", true)));
                    int actual = audio.getStreamVolume(android.media.AudioManager.STREAM_MUSIC); check(actual != before); check(reply.get().startsWith("Громкость музыки"));
                    for (String command : new String[]{"Сколько сейчас времени?", "Какая сегодня дата?", "Уровень заряда"}) {
                        onMain(() -> new PhoneActionEngine(activity, reply::set, null, () -> true).execute(PhoneCommands.parse(command, true)));
                        check(reply.get().startsWith("Сейчас ") || reply.get().startsWith("Сегодня ") || reply.get().startsWith("Заряд батареи: "));
                    }
                    result.putString("volume_probe", new org.json.JSONObject().put("before", before).put("changed_to", actual).put("maximum", maximum).put("restored", true).toString());
                } finally { audio.setStreamVolume(android.media.AudioManager.STREAM_MUSIC, before, 0); onMain(activity::finish); check(audio.getStreamVolume(android.media.AudioManager.STREAM_MUSIC) == before); }
            });
            if (setupApps) test("userSelectedPreferredApps", () -> {
                android.content.SharedPreferences preferences = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE);
                AppCatalog[] catalog = new AppCatalog[1]; java.util.concurrent.CountDownLatch scanned = new java.util.concurrent.CountDownLatch(1);
                try {
                    onMain(() -> catalog[0] = new AppCatalog(context, preferences, () -> { if (!catalog[0].scanning()) scanned.countDown(); }));
                    check(scanned.await(10, java.util.concurrent.TimeUnit.SECONDS));
                    for (String[] choice : new String[][]{{"messenger", "app.nimarkogram.messenger", "Телеграм"}, {"music", "ru.mts.music.android", "музыку"}}) {
                        AppRegistry.App selected = null; for (AppRegistry.App app : catalog[0].entries()) if (app.packageName().equals(choice[1])) { selected = app; break; }
                        check(selected != null); check(preferences.edit().putString("preferred_" + choice[0], selected.id()).commit());
                        java.util.concurrent.CountDownLatch resolved = new java.util.concurrent.CountDownLatch(1); java.util.concurrent.atomic.AtomicBoolean correct = new java.util.concurrent.atomic.AtomicBoolean();
                        catalog[0].resolve(choice[2], matches -> { correct.set(matches.size() == 1 && matches.get(0).packageName().equals(choice[1])); resolved.countDown(); });
                        check(resolved.await(5, java.util.concurrent.TimeUnit.SECONDS)); check(correct.get());
                    }
                } finally { if (catalog[0] != null) onMain(catalog[0]::close); }
            });
            if (llmProbe) test("installedQwenGeneratesOnDevice", () -> {
                java.nio.file.Path model = LlmModels.readActive(context.getFilesDir().toPath().resolve("llm-models")); check(model != null); check(LocalLlmNative.supported());
                LocalLlm engine = new LocalLlm(context); java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
                java.util.concurrent.atomic.AtomicReference<String> answer = new java.util.concurrent.atomic.AtomicReference<>(), failure = new java.util.concurrent.atomic.AtomicReference<>(); long began = android.os.SystemClock.elapsedRealtime();
                try {
                    engine.generate(model, LocalLlm.prompt(java.util.Arrays.asList(new LocalChatRepository.Message("user", "Сколько будет два плюс два? Ответь одним числом."))), new LocalLlm.Listener() {
                        public void state(String text) {} public void partial(String text) {} public void done(String text, boolean stopped) { answer.set(text); }
                        public void error(String text) { failure.set(text); } public void finished() { done.countDown(); }
                    });
                    check(done.await(100, java.util.concurrent.TimeUnit.SECONDS)); if (failure.get() != null) throw new AssertionError(failure.get());
                    result.putString("llm_probe", new org.json.JSONObject().put("answer", answer.get()).put("elapsed_ms", android.os.SystemClock.elapsedRealtime() - began).put("native", true).put("model_bytes", LlmModels.BYTES).toString());
                    if (!four(answer.get())) throw new AssertionError("Проверочный ответ Qwen: " + answer.get());
                } finally { engine.close(); }
            });
            if (llmProbe) test("phoneChatAnswersAndPersists", () -> {
                android.content.SharedPreferences preferences = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE);
                String originalChat = preferences.getString("phone_chat", null), originalDraft = preferences.getString("phone_draft", ""); boolean originalVoice = preferences.getBoolean("read_aloud", false);
                Activity[] activity = new Activity[1]; String testId = null;
                try (LocalChatRepository repository = new LocalChatRepository(context)) {
                    try {
                        testId = repository.submit("", "Проверка локального чата Codex"); check(preferences.edit().putString("phone_chat", testId).putBoolean("read_aloud", false).commit());
                        activity[0] = startActivitySync(new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                        boolean[] enabled = {false}; long deadline = android.os.SystemClock.elapsedRealtime() + 5000;
                        while (!enabled[0] && android.os.SystemClock.elapsedRealtime() < deadline) { onMain(() -> enabled[0] = find(activity[0].getWindow().getDecorView(), "Отправить сообщение").isEnabled()); Thread.sleep(30); } check(enabled[0]);
                        onMain(() -> { android.view.View root = activity[0].getWindow().getDecorView(); android.widget.EditText field = firstInput(root); check(field != null); field.setText("Сколько будет два плюс два? Ответь одним числом."); click(activity[0], "Отправить сообщение"); });
                        String answer = ""; deadline = android.os.SystemClock.elapsedRealtime() + 100000;
                        while (android.os.SystemClock.elapsedRealtime() < deadline) { for (LocalChatRepository.Message message : repository.messages(testId)) if (message.role().equals("assistant")) answer = message.content(); if (!answer.isEmpty()) break; Thread.sleep(100); }
                        result.putString("chat_probe", new org.json.JSONObject().put("answer", answer).put("persisted", true).put("test_chat_removed", true).toString()); if (!four(answer)) throw new AssertionError("Проверочный ответ чата: " + answer);
                    } finally {
                        if (activity[0] != null) { onMain(activity[0]::finish); waitForIdleSync(); }
                        if (testId != null) repository.delete(testId);
                        android.content.SharedPreferences.Editor restore = preferences.edit().putString("phone_draft", originalDraft).putBoolean("read_aloud", originalVoice);
                        if (originalChat == null) restore.remove("phone_chat"); else restore.putString("phone_chat", originalChat); check(restore.commit());
                    }
                }
            });
            result.putString("stream", "\nWileyAI Android: " + current + " tests passed\n"); finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            result.putString("shortMsg", failure.toString()); result.putString("stream", "\nFAILED after " + current + " tests: " + failure + "\n"); finish(Activity.RESULT_CANCELED, result);
        } finally { context.deleteDatabase(DATABASE); }
    }
    private static boolean four(String answer) { return answer != null && answer.trim().matches("(?iu)(?:4|четыре|два плюс два равно (?:четыре|4))[.! ]*"); }
    private static android.widget.EditText firstInput(android.view.View view) { if (view instanceof android.widget.EditText) return (android.widget.EditText)view; if (view instanceof android.view.ViewGroup) { android.view.ViewGroup group = (android.view.ViewGroup)view; for (int i = 0; i < group.getChildCount(); i++) { android.widget.EditText input = firstInput(group.getChildAt(i)); if (input != null) return input; } } return null; }
}
