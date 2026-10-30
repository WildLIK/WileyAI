package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.*;
import android.content.pm.*;
import android.os.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.JSONObject;

final class AssistantProbe {
    private static void check(boolean value) { if (!value) throw new AssertionError("Assistant probe failed"); }
    static void metadata(Context context) throws Exception {
        ComponentName component = new ComponentName(context, WileyVoiceService.class);
        ServiceInfo info = context.getPackageManager().getServiceInfo(component, PackageManager.GET_META_DATA);
        check("android.permission.BIND_VOICE_INTERACTION".equals(info.permission));
        try (android.content.res.XmlResourceParser xml = info.loadXmlMetaData(context.getPackageManager(), "android.voice_interaction")) {
            while (xml.next() != org.xmlpull.v1.XmlPullParser.START_TAG) {}
            String ns = "http://schemas.android.com/apk/res/android";
            check(xml.getName().equals("voice-interaction-service")); check(xml.getAttributeValue(ns, "sessionService").equals(WileySessionService.class.getName()));
            check(xml.getAttributeValue(ns, "recognitionService").equals(WileyRecognitionService.class.getName())); check(xml.getAttributeBooleanValue(ns, "supportsAssist", false));
        }
        ServiceInfo microphone = context.getPackageManager().getServiceInfo(new ComponentName(context, HandsFreeService.class), 0);
        check(!microphone.exported); if (Build.VERSION.SDK_INT >= 29) check((microphone.getForegroundServiceType() & ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) != 0);
        ServiceInfo recognizer = context.getPackageManager().getServiceInfo(new ComponentName(context, WileyRecognitionService.class), 0);
        check("android.permission.BIND_SPEECH_RECOGNITION_SERVICE".equals(recognizer.permission));
    }
    static String googleVoice(Instrumentation runner, Context context) throws Exception {
        check(context.getPackageManager().getApplicationInfo("com.google.android.tts", 0).enabled);
        SharedPreferences preferences = context.getSharedPreferences("wiley-mobile", 0);
        check(preferences.edit().putString("offline_engine", "com.google.android.tts").remove("offline_voice").putFloat("offline_voice_rate", 1.1f).putFloat("offline_voice_pitch", 1.08f).commit());
        LocalVoice[] voice = new LocalVoice[1]; CountDownLatch ready = new CountDownLatch(1), spoken = new CountDownLatch(1); AtomicReference<String> error = new AtomicReference<>(), name = new AtomicReference<>(); AtomicInteger completions = new AtomicInteger();
        try {
            runner.runOnMainSync(() -> { voice[0] = new LocalVoice(context, preferences, text -> { error.set(text); ready.countDown(); spoken.countDown(); }); voice[0].ready(ready::countDown); });
            check(ready.await(20, TimeUnit.SECONDS)); if (error.get() != null) throw new AssertionError(error.get());
            runner.runOnMainSync(() -> {
                check(!voice[0].voices().isEmpty()); name.set(voice[0].voices().get(0).getName()); voice[0].select(name.get());
                voice[0].speakCompleted("Привет! Я Уайли. Теперь можно вызвать меня голосом и сразу сказать команду.", () -> { completions.incrementAndGet(); spoken.countDown(); });
            });
            check(spoken.await(30, TimeUnit.SECONDS)); if (error.get() != null) throw new AssertionError(error.get()); check(completions.get() == 1);
            return new JSONObject().put("engine", "com.google.android.tts").put("voice", name.get()).put("rate", 1.1).put("pitch", 1.08).put("completed", true).toString();
        } finally { if (voice[0] != null) runner.runOnMainSync(voice[0]::close); }
    }
    static void history(Instrumentation runner, Context context) throws Exception {
        String database = "assistant-probe.db"; context.deleteDatabase(database);
        SharedPreferences preferences = context.getSharedPreferences("assistant-probe", 0); preferences.edit().clear().putString("phone_chat", "untouched").putString("phone_draft", "draft").commit();
        AssistantConversation[] history = new AssistantConversation[1]; AtomicReference<String> id = new AtomicReference<>(), error = new AtomicReference<>(); CountDownLatch first = new CountDownLatch(1), second = new CountDownLatch(1);
        try {
            runner.runOnMainSync(() -> { history[0] = new AssistantConversation(new LocalChatRepository(context, database), preferences); history[0].submit("Первый запрос", (chat, messages) -> { id.set(chat); check(messages.size() == 1); history[0].reply(chat,"Первый ответ"); first.countDown(); }, text -> { error.set(text); first.countDown(); }); });
            check(first.await(10, TimeUnit.SECONDS)); check(error.get() == null);
            runner.runOnMainSync(() -> history[0].submit("Второй запрос", (chat, messages) -> { check(chat.equals(id.get())); check(messages.size() == 3); second.countDown(); }, text -> { error.set(text); second.countDown(); }));
            check(second.await(10, TimeUnit.SECONDS)); check(error.get() == null);
            check(preferences.getString("phone_chat", "").equals("untouched")); check(preferences.getString("phone_draft", "").equals("draft"));
        } finally { if (history[0] != null) runner.runOnMainSync(history[0]::close); preferences.edit().clear().commit(); }
        // The close is queued after writes. Reopening must see their committed data.
        try (LocalChatRepository repository = new LocalChatRepository(context, database)) { check(repository.messages(id.get()).size() == 3); }
        context.deleteDatabase(database);
    }
    static String vocabulary(Context context) throws Exception {
        java.nio.file.Path path = VerifiedModelInstaller.active(context.getFilesDir().toPath().resolve("speech-models")); check(path != null); JSONObject result = new JSONObject();
        try (org.vosk.Model model = new org.vosk.Model(path.toString())) {
            for (String word : new String[]{"окей", "о", "кей", "вайли", "уайли", "вай", "ли", "вали", "привет", "помощник"}) result.put(word, WakeVocabulary.contains(model, word));
        }
        return result.toString();
    }
    static String temporalRouting(Context context)throws Exception{
        String chat=context.getSharedPreferences("wiley-mobile",0).getString("assistant_chat","");org.json.JSONArray queries=new org.json.JSONArray();
        try(LocalChatRepository repository=new LocalChatRepository(context)){
            for(LocalChatRepository.Message message:repository.messages(chat,16))if(message.role().equals("user")&&message.content().length()<=120&&message.content().toLowerCase(java.util.Locale.ROOT).matches(".*(?:врем|час|дат|число).*")){
                PhoneCommands.Action action=PhoneCommands.parse(message.content(),true);queries.put(new JSONObject().put("heard",message.content()).put("route",action==null?"llm":action.kind+":"+action.value));
            }
        }
        return new JSONObject().put("android_time",java.time.ZonedDateTime.now().toString()).put("temporal_queries",queries).toString();
    }
    static void temporalClock(Instrumentation runner,Context context)throws Exception{
        for(String query:new String[]{"время какое","А время?","сколько сейчас время","который сейчас час"}){
            PhoneCommands.Action action=PhoneCommands.parse(query,true);check(action!=null&&action.kind.equals("info")&&action.value.equals("time"));
            AtomicReference<String> reply=new AtomicReference<>();String before=java.time.ZonedDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"));
            runner.runOnMainSync(()->PhoneActionCore.execute(context,action,reply::set));String after=java.time.ZonedDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"));
            check(reply.get().equals("Сейчас "+before+" по времени телефона.")||reply.get().equals("Сейчас "+after+" по времени телефона."));
        }
        String math=LocalLlm.prompt(java.util.Arrays.asList(new LocalChatRepository.Message("user","Сколько будет два плюс два? Ответь одним числом.")));check(!math.contains("Системные дата"));
        String temporal=LocalLlm.prompt(java.util.Arrays.asList(new LocalChatRepository.Message("user","Почему 15 часов?")));check(temporal.contains("Системные дата")&&temporal.contains(java.time.ZoneId.systemDefault().getId()));
    }
    private AssistantProbe() {}
}
