package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

final class LocalProvider implements BrainProvider {
    private final Context context;private final LocalLlm engine;
    LocalProvider(Context context){this.context=context;engine=new LocalLlm(context);}
    public Kind kind(){return Kind.LOCAL;}public boolean nativeTools(){return false;}
    public Completion complete(List<Map<String,Object>> messages,List<AndroidTools.Tool> tools,boolean planning,Cancellation cancel,Consumer<String> status)throws Exception{
        Path model=LlmModels.readActive(context.getFilesDir().toPath().resolve("llm-models"));if(model==null)throw new Exception("Установите локальную модель в «Настройки → Мозг → Локальная модель».");
        StringBuilder prompt=new StringBuilder();for(Map<String,Object> item:messages){String role=(String)item.get("role");String value=String.valueOf(item.getOrDefault("content","")).replace("<|","< | ");prompt.append("<|im_start|>").append(role.equals("system")?"system":role.equals("assistant")?"assistant":"user").append('\n').append(value).append("<|im_end|>\n");}prompt.append("<|im_start|>assistant\n<think>\n\n</think>\n\n");
        CountDownLatch finished=new CountDownLatch(1);AtomicReference<String> text=new AtomicReference<>(""),error=new AtomicReference<>();cancel.onCancel(engine::cancel);
        String grammar=planning?StructuredActionAdapter.grammar(tools,StructuredActionAdapter.maxSteps(String.valueOf(messages.get(messages.size()-1).get("content")))):null;
        new Handler(Looper.getMainLooper()).post(()->engine.generate(model,prompt.toString(),grammar,new LocalLlm.Listener(){public void state(String value){status.accept(planning?"Модель составляет план…":value);}public void partial(String value){}public void done(String value,boolean stopped){if(stopped)error.set("Запрос отменён");else text.set(value);}public void error(String value){error.set(value);}public void finished(){finished.countDown();}}));
        long deadline=SystemClock.elapsedRealtime()+95000;while(!finished.await(100,TimeUnit.MILLISECONDS)){cancel.check();if(SystemClock.elapsedRealtime()>deadline){engine.cancel();throw new Exception("Модель не завершила ответ вовремя.");}}cancel.check();if(error.get()!=null)throw new Exception(error.get());return new Completion(text.get(),List.of());
    }
    public void close(){engine.close();}
}
