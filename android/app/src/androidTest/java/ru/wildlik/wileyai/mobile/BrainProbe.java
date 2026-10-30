package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.content.*;
import android.media.AudioManager;
import android.os.*;
import org.json.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Actual installed local model, validator and Android executor. No downloaded models or cloud account. */
final class BrainProbe {
    private static void check(boolean value,String stage){if(!value)throw new AssertionError("Brain probe: "+stage);}
    static String plans(Instrumentation runner,Context context)throws Exception{
        JSONArray reports=new JSONArray();
        for(String[] item:new String[][]{{"Будь добра, установи для музыки 30 процентов громкости","set_volume"},{"Открой настройки Bluetooth","open_bluetooth_settings"},{"Поставь будильник на 7 утра","create_alarm"},{"Открой Telegram и сделай громкость 30 процентов","open_app,set_volume"}}){
            long started=SystemClock.elapsedRealtime();List<AndroidTools.Tool> tools=StructuredActionAdapter.relevant(item[0]);
            try(LocalProvider provider=new LocalProvider(context)){
                BrainProvider.Completion completion=provider.complete(List.of(Map.of("role","system","content",StructuredActionAdapter.instruction(tools,java.time.ZonedDateTime.now().toString())),Map.of("role","user","content",item[0])),tools,true,new BrainProvider.Cancellation(),s->{});
                AndroidTools.Plan plan;try{plan=StructuredActionAdapter.parse(completion.text(),tools);}catch(Exception error){throw new AssertionError("Invalid plan for "+item[0]+": "+completion.text(),error);}Set<String> actual=new HashSet<>();for(var call:plan.steps())actual.add(call.tool());
                reports.put(new JSONObject().put("request",item[0]).put("output",completion.text()).put("elapsed_ms",SystemClock.elapsedRealtime()-started));
                if(item[1].isEmpty()){check(plan.steps().isEmpty()&&plan.reply().contains("4"),"ordinary conversation: "+completion.text());continue;}
                for(String name:item[1].split(","))check(actual.contains(name),"expected "+name+"; model output: "+completion.text());
                Set<String> expected=new HashSet<>(List.of(item[1].split(",")));expected.add("get_volume");check(expected.containsAll(actual),"unrequested tools: "+completion.text());check(new HashSet<>(plan.steps()).size()==plan.steps().size(),"duplicate steps: "+completion.text());
                for(var call:plan.steps()){if(call.tool().equals("set_volume"))check(Integer.valueOf(30).equals(call.arguments().get("percent")),"requested volume value");if(call.tool().equals("create_alarm"))check(Integer.valueOf(7).equals(call.arguments().get("hour"))&&Integer.valueOf(0).equals(call.arguments().get("minute")),"requested alarm time");}
            }
        }return reports.toString();
    }
    static String conversation(Instrumentation runner,Context context)throws Exception{
        BrainController[] brain={null};CountDownLatch finished=new CountDownLatch(1);AtomicReference<String> answer=new AtomicReference<>(),error=new AtomicReference<>();AppCatalog[] apps={null};
        try{runner.runOnMainSync(()->{apps[0]=new AppCatalog(context,context.getSharedPreferences("wiley-mobile",0),()->{});brain[0]=new BrainController(context,apps[0]);brain[0].generate(List.of(new LocalChatRepository.Message("user","Сколько будет два плюс два? Ответь цифрой.")),new BrainController.Host(){public boolean active(){return true;}public void state(String value){}public void confirm(String plan,java.util.function.Consumer<Boolean> reply){reply.accept(false);error.set("Unexpected confirmation");}public void launch(Intent intent){throw new AssertionError("Unexpected launch");}public void done(String value){answer.set(value);}public void error(String value){error.set(value);}public void finished(){finished.countDown();}});});check(finished.await(100,TimeUnit.SECONDS),"conversation deadline");check(error.get()==null&&answer.get()!=null&&answer.get().trim().toLowerCase(Locale.ROOT).matches("(?:4|четыре|два плюс два равно (?:четыре|4))[.! ]*"),"ordinary answer: "+answer.get()+" / "+error.get());return new JSONObject().put("actual_local_model",true).put("answer",answer.get()).put("tools_executed",0).toString();}
        finally{if(brain[0]!=null)runner.runOnMainSync(brain[0]::close);if(apps[0]!=null)runner.runOnMainSync(apps[0]::close);}
    }
    static String loop(Instrumentation runner,Context context)throws Exception{
        AtomicReference<AppCatalog> catalog=new AtomicReference<>();CountDownLatch scanned=new CountDownLatch(1);
        runner.runOnMainSync(()->catalog.set(new AppCatalog(context,context.getSharedPreferences("wiley-mobile",0),()->{if(catalog.get()!=null&&!catalog.get().scanning())scanned.countDown();})));check(scanned.await(10,TimeUnit.SECONDS),"app catalog");
        BrainController[] brain={null};AudioManager audio=(AudioManager)context.getSystemService(Context.AUDIO_SERVICE);int before=audio.getStreamVolume(AudioManager.STREAM_MUSIC);int targetPercent=before==Math.round(audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)*.3f)?40:30;
        try{
            runner.runOnMainSync(()->brain[0]=new BrainController(context,catalog.get()));CountDownLatch finished=new CountDownLatch(1);AtomicReference<String> answer=new AtomicReference<>(),error=new AtomicReference<>();AtomicBoolean confirmed=new AtomicBoolean();
            runner.runOnMainSync(()->brain[0].generate(List.of(new LocalChatRepository.Message("user","Будь добра, установи для музыки "+targetPercent+" процентов громкости")),new BrainController.Host(){public boolean active(){return true;}public void state(String text){}public void confirm(String plan,java.util.function.Consumer<Boolean> callback){confirmed.set(true);callback.accept(true);}public void launch(Intent intent){throw new AssertionError("Unexpected launch");}public void done(String text){answer.set(text);}public void error(String text){error.set(text);}public void finished(){finished.countDown();}}));
            check(finished.await(100,TimeUnit.SECONDS),"brain deadline");check(confirmed.get(),"model plan confirmation");check(audio.getStreamVolume(AudioManager.STREAM_MUSIC)==Math.round(audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)*targetPercent/100f),"real volume changed; actual="+audio.getStreamVolume(AudioManager.STREAM_MUSIC)+"; answer="+answer.get()+"; error="+error.get());check(answer.get()!=null,"result missing: "+error.get());return new JSONObject().put("confirmation_requested",true).put("answer",answer.get()).put("before",before).put("actual",audio.getStreamVolume(AudioManager.STREAM_MUSIC)).put("restored",true).toString();
        }finally{audio.setStreamVolume(AudioManager.STREAM_MUSIC,before,0);if(brain[0]!=null)runner.runOnMainSync(brain[0]::close);runner.runOnMainSync(catalog.get()::close);}
    }
    static String nativeFixture(Instrumentation runner,Context context)throws Exception{
        check(new ModelManager(context).selected()==BrainProvider.Kind.LOCAL,"fixture requires local selection; no account settings are changed");
        AtomicReference<AppCatalog> apps=new AtomicReference<>();CountDownLatch scanned=new CountDownLatch(1);
        runner.runOnMainSync(()->apps.set(new AppCatalog(context,context.getSharedPreferences("wiley-mobile",0),()->{if(apps.get()!=null&&!apps.get().scanning())scanned.countDown();})));check(scanned.await(10,TimeUnit.SECONDS),"catalog");
        AudioManager audio=(AudioManager)context.getSystemService(Context.AUDIO_SERVICE);int before=audio.getStreamVolume(AudioManager.STREAM_MUSIC),max=audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC),percent=before==Math.round(max*.3f)?40:30;JSONArray cases=new JSONArray();
        boolean locked=((KeyguardManager)context.getSystemService(Context.KEYGUARD_SERVICE)).isDeviceLocked();
        try{for(String mode:List.of(locked?"locked":"execute","deny","cancel","invalid","duplicate")){
            AtomicInteger rounds=new AtomicInteger();AtomicBoolean returnedResult=new AtomicBoolean(),confirmed=new AtomicBoolean();CountDownLatch finished=new CountDownLatch(1);AtomicReference<String> answer=new AtomicReference<>(),error=new AtomicReference<>();BrainController[] brain={null};
            BrainProvider fake=new BrainProvider(){public Kind kind(){return Kind.OFFICIAL_API;}public boolean nativeTools(){return true;}public Completion complete(List<Map<String,Object>> messages,List<AndroidTools.Tool> tools,boolean planning,Cancellation cancel,java.util.function.Consumer<String> status)throws Exception{
                int round=rounds.incrementAndGet();cancel.check();
                if(mode.equals("duplicate"))return new Completion("",List.of(new Call("one","set_volume","{\"percent\":"+percent+"}"),new Call("two","set_volume","{\"percent\":"+percent+"}")));
                if(mode.equals("invalid"))return new Completion("",List.of(new Call("bad","run_shell","{\"command\":\"echo no\"}")));
                if(round==1)return new Completion("",List.of(new Call("volume-call","set_volume","{\"percent\":"+percent+"}"),new Call("read-call","get_volume","{}")));
                List<Map<String,Object>> replies=new ArrayList<>();for(Map<String,Object> message:messages)if(message.get("role").equals("tool"))replies.add(message);
                check(replies.size()==2,"native results returned");check(replies.get(0).get("tool_call_id").equals("volume-call"),"native ID preserved");check(new JSONObject((String)replies.get(0).get("content")).getString("status").equals("verified"),"actual verification returned");returnedResult.set(true);return new Completion("Выдуманное сообщение об успехе не должно заменить факты.",List.of());
            }};
            runner.runOnMainSync(()->{brain[0]=new BrainController(context,apps.get(),()->fake);brain[0].generate(List.of(new LocalChatRepository.Message("user","Установи громкость музыки "+percent+" процентов и проверь громкость")),new BrainController.Host(){public boolean active(){return true;}public void state(String text){}public void confirm(String plan,java.util.function.Consumer<Boolean> callback){confirmed.set(true);if(mode.equals("cancel"))brain[0].cancel();callback.accept(!mode.equals("deny"));}public void launch(Intent intent){throw new AssertionError("Unexpected launch");}public void done(String text){answer.set(text);}public void error(String text){error.set(text);}public void finished(){finished.countDown();}});});
            try{check(finished.await(15,TimeUnit.SECONDS),"native fixture deadline");if(mode.equals("execute")){check(confirmed.get()&&returnedResult.get()&&rounds.get()==2,"native loop continued after consent and results");check(audio.getStreamVolume(AudioManager.STREAM_MUSIC)==Math.round(max*percent/100f),"native fixture actual volume");check(answer.get()!=null&&!answer.get().contains("Выдуманное"),"factual final reply");}else{check(mode.equals("locked")?answer.get()!=null&&answer.get().contains("Разблокируйте"):error.get()!=null,"rejection reported: "+mode);check(audio.getStreamVolume(AudioManager.STREAM_MUSIC)==before,"rejected plan had no effect");check(!returnedResult.get(),"no followup after rejected plan");}cases.put(new JSONObject().put("scenario",mode).put("model_fixture",true).put("passed",true));}
            finally{runner.runOnMainSync(brain[0]::close);audio.setStreamVolume(AudioManager.STREAM_MUSIC,before,0);}
        }return cases.toString();}finally{runner.runOnMainSync(apps.get()::close);}
    }
}
