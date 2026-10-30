package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.*;
import android.os.*;
import org.json.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

final class IterationNineProbe {
    static void check(boolean value){if(!value)throw new AssertionError("Iteration nine assertion failed");}
    static String history(Instrumentation runner,Context context)throws Exception{
        SharedPreferences real=context.getSharedPreferences("wiley-mobile",0);boolean exists;String pointer=real.getString("assistant_chat","");
        try(LocalChatRepository repository=new LocalChatRepository(context)){exists=!pointer.isEmpty()&&repository.chat(pointer)!=null;}
        String name="iteration-nine-history.db";context.deleteDatabase(name);SharedPreferences isolated=context.getSharedPreferences("iteration-nine",0);isolated.edit().clear().commit();
        try{
            String deleted,untouched;
            try(LocalChatRepository repository=new LocalChatRepository(context,name)){
                untouched=repository.submit("","Сохранённый чат");deleted=repository.submit("","Удалённый чат");repository.delete(deleted);
            }
            isolated.edit().putString("assistant_chat",deleted).putString("phone_chat",untouched).putString("phone_draft","Черновик").commit();
            AssistantConversation[] history=new AssistantConversation[1];CountDownLatch done=new CountDownLatch(1);AtomicReference<String> id=new AtomicReference<>(),failure=new AtomicReference<>();
            runner.runOnMainSync(()->{history[0]=new AssistantConversation(new LocalChatRepository(context,name),isolated);history[0].submit("включи музыку",(chat,messages)->{id.set(chat);done.countDown();},error->{failure.set(error);done.countDown();});});
            check(done.await(10,TimeUnit.SECONDS));check(failure.get()==null);check(id.get()!=null&&!id.get().equals(deleted));
            runner.runOnMainSync(history[0]::close);
            try(LocalChatRepository repository=new LocalChatRepository(context,name)){check(repository.chat(untouched)!=null);check(repository.messages(untouched).size()==1);check(repository.messages(id.get()).size()==1);}
            check(isolated.getString("phone_chat","").equals(untouched));check(isolated.getString("phone_draft","").equals("Черновик"));
            return new JSONObject().put("production_pointer_present",!pointer.isEmpty()).put("production_chat_exists",exists).put("deleted_chat_recovered",true).put("other_chat_and_draft_preserved",true).toString();
        }finally{isolated.edit().clear().commit();context.deleteDatabase(name);}
    }
    static String cache(Context context)throws Exception{
        java.nio.file.Path path=VerifiedModelInstaller.active(context.getFilesDir().toPath().resolve("speech-models"));check(path!=null);
        long began=SystemClock.elapsedRealtime();org.vosk.Model cached;
        try(SpeechRuntime.Lease first=SpeechRuntime.acquire(path)){cached=first.model();try(SpeechRuntime.Lease second=SpeechRuntime.acquire(path)){check(first.model()==second.model());try(org.vosk.Recognizer a=new org.vosk.Recognizer(first.model(),16000);org.vosk.Recognizer b=new org.vosk.Recognizer(second.model(),16000)){check(a!=b);}}}
        long firstMillis=SystemClock.elapsedRealtime()-began;began=SystemClock.elapsedRealtime();
        try(SpeechRuntime.Lease warm=SpeechRuntime.acquire(path);org.vosk.Recognizer decoder=new org.vosk.Recognizer(warm.model(),16000)){check(warm.model()==cached);}
        return new JSONObject().put("initial_model_and_two_decoders_ms",firstMillis).put("warm_model_and_decoder_ms",SystemClock.elapsedRealtime()-began).put("shared_weights_separate_decoders",true).toString();
    }
    static void parsers()throws Exception{
        String video="var ytInitialData = {\"contents\":[{\"videoRenderer\":{\"videoId\":\"aqz-KE-bpKQ\",\"title\":{\"runs\":[{\"text\":\"Big {Buck} \\\"Bunny\\\"\"}]},\"ownerText\":{\"simpleText\":\"Blender\"}}},{\"videoRenderer\":{\"videoId\":\"aqz-KE-bpKQ\",\"title\":{\"simpleText\":\"Duplicate\"}}},{\"videoRenderer\":{\"videoId\":\"bad;id\",\"title\":{\"simpleText\":\"Bad\"}}}]} ;";
        List<YoutubeSearch.Video> videos=YoutubeSearch.parse(video);check(videos.size()==1);check(videos.get(0).title().equals("Big {Buck} \"Bunny\""));check(YoutubeSearch.parse("consent page").isEmpty());
        JSONObject payload=CloudChat.payload("qwen-test",Arrays.asList(new LocalChatRepository.Message("user","Привет")));check(!payload.has("tools"));check(payload.getJSONArray("messages").getJSONObject(1).getString("content").equals("Привет"));
        for(String endpoint:new String[]{"http://example.com/v1","https://user:pass@example.com/v1","https://example.com/v1?token=secret","https://example.com/#frag"}){boolean rejected=false;try{CloudChat.validate(new JSONObject().put("endpoint",endpoint).put("model","qwen").put("key",""));}catch(Exception expected){rejected=true;}check(rejected);}
        CloudChat.validate(new JSONObject().put("endpoint","https://example.com/v1").put("model","qwen-3").put("key","test"));
        check(CloudChat.httpError(429).contains("лимит"));check(CloudChat.httpError(302).contains("перенаправляет"));
    }
    static String publicYoutube(Context context)throws Exception{
        AtomicReference<List<YoutubeSearch.Video>> result=new AtomicReference<>();CountDownLatch done=new CountDownLatch(1);YoutubeSearch.find("Big Buck Bunny Blender Foundation",videos->{result.set(videos);done.countDown();});check(done.await(22,TimeUnit.SECONDS));
        JSONObject report=new JSONObject().put("results",result.get().size()).put("public_query_only",true);if(!result.get().isEmpty())report.put("first_id",result.get().get(0).id()).put("first_title",result.get().get(0).title());return report.toString();
    }
    static void cloudTransport(Instrumentation runner,Context context)throws Exception{
        SettingsRepository isolated=new SettingsRepository(context,"cloud-iteration-nine");isolated.preferences.edit().clear().commit();
        try{
            JSONObject config=new JSONObject().put("endpoint","https://example.com/v1").put("model","qwen-test").put("key","test_secret_123");isolated.saveCloud(config);
            check(!isolated.preferences.getString("cloud_connection","").contains("test_secret_123"));check(isolated.readCloud().getString("key").equals("test_secret_123"));check(!isolated.preferences.getBoolean("cloud_enabled",true));
            isolated.preferences.edit().putBoolean("cloud_enabled",true).commit();
            for(int status:new int[]{200,302,401,429}){
                AtomicInteger calls=new AtomicInteger();AtomicReference<FakeConnection> connection=new AtomicReference<>();
                CloudChat chat=new CloudChat(isolated,address->{check(address.equals("https://example.com/v1/chat/completions"));calls.incrementAndGet();FakeConnection fake=new FakeConnection(status);connection.set(fake);return fake;});
                AtomicReference<String> answer=new AtomicReference<>(),error=new AtomicReference<>();CountDownLatch done=new CountDownLatch(1);
                try{
                    runner.runOnMainSync(()->chat.generate(Arrays.asList(new LocalChatRepository.Message("user","Публичная проверка")),new LocalLlm.Listener(){public void state(String value){}public void partial(String value){}public void done(String value,boolean stopped){answer.set(value);}public void error(String value){error.set(value);}public void finished(){done.countDown();}}));
                    check(done.await(5,TimeUnit.SECONDS));check(calls.get()==1);check(!connection.get().getInstanceFollowRedirects());check(connection.get().getRequestProperty("Authorization").equals("Bearer test_secret_123"));
                    JSONObject body=new JSONObject(connection.get().body.toString("UTF-8"));check(!body.has("tools"));check(body.getJSONArray("messages").length()==2);check(!body.getBoolean("stream"));
                    if(status==200)check(answer.get().equals("Готова"));else check(answer.get()==null&&error.get()!=null);
                }finally{runner.runOnMainSync(chat::close);}
            }
        }finally{isolated.preferences.edit().clear().commit();}
    }
    private static final class FakeConnection extends java.net.HttpURLConnection{
        final int status;final java.io.ByteArrayOutputStream body=new java.io.ByteArrayOutputStream();
        FakeConnection(int status)throws java.net.MalformedURLException{super(new java.net.URL("https://example.com"));this.status=status;}
        public void disconnect(){}public boolean usingProxy(){return false;}public void connect(){}public int getResponseCode(){return status;}
        public java.io.OutputStream getOutputStream(){return body;}
        public java.io.InputStream getInputStream(){return new java.io.ByteArrayInputStream("{\"choices\":[{\"message\":{\"content\":\"Готова\"}}]}".getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    }
    private IterationNineProbe(){}
}
