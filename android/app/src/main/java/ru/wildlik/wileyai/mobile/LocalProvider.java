package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

final class LocalProvider implements BrainProvider {
    private final Context context;private final LocalLlmRuntime runtime;private volatile LocalModelSession.Ticket active;private volatile boolean closed;
    LocalProvider(Context context){this.context=context.getApplicationContext();runtime=LocalLlmRuntime.get(context);}
    public Kind kind(){return Kind.LOCAL;}public boolean nativeTools(){return false;}
    public Completion complete(List<Map<String,Object>> messages,List<AndroidTools.Tool> tools,boolean planning,Cancellation cancel,Consumer<String> status)throws Exception{
        Path model=LlmModels.readActive(context.getFilesDir().toPath().resolve("llm-models"));if(model==null)throw new Exception("Установите локальную модель в «Настройки → Мозг → Локальная модель».");
        StringBuilder prompt=new StringBuilder();for(Map<String,Object> item:messages){String role=(String)item.get("role");String value=String.valueOf(item.getOrDefault("content","")).replace("<|","< | ");prompt.append("<|im_start|>").append(role.equals("system")?"system":role.equals("assistant")?"assistant":"user").append('\n').append(value).append("<|im_end|>\n");}prompt.append("<|im_start|>assistant\n<think>\n\n</think>\n\n");
        if(closed)throw new Exception("Локальный провайдер закрыт");cancel.check();
        String grammar=planning?StructuredActionAdapter.grammar(tools,StructuredActionAdapter.maxSteps(String.valueOf(messages.get(messages.size()-1).get("content")))):null;
        runtime.profileChanged();
        LocalModelSession.Ticket ticket=runtime.session.generate(LocalLlmRuntime.model(model),prompt.toString(),grammar,
            cold->status.accept(planning?"Модель составляет план…":cold?"Загружаю модель телефона…":"Использую загруженную модель телефона…"),text->{},cancel::firstOutput);
        active=ticket;cancel.onCancel(ticket::cancel);if(closed)ticket.cancel();
        long deadline=SystemClock.elapsedRealtime()+95000;
        try {
            while(true){cancel.check();try{
                LocalModelSession.Output output=ticket.result.get(100,TimeUnit.MILLISECONDS);cancel.check();
                if(output.stopped())throw new Exception("Запрос остановлен");return new Completion(output.text(),List.of());
            }catch(TimeoutException waiting){if(SystemClock.elapsedRealtime()>deadline){ticket.cancel();throw new Exception("Модель не завершила ответ вовремя.");}}}
        }catch(ExecutionException failed){throw new Exception(LocalLlm.safeError(failed));}
        finally{ticket.cancel();if(active==ticket)active=null;}
    }
    public void close(){closed=true;LocalModelSession.Ticket ticket=active;if(ticket!=null)ticket.cancel();}
}
