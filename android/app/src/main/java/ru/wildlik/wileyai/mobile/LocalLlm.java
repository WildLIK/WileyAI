package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.*;
import java.io.*;
import java.nio.*;
import java.nio.charset.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** CPU-only UI facade over the one process-wide model owner. */
final class LocalLlm {
    interface Listener { void state(String text); void partial(String text); void done(String text, boolean stopped); void error(String text); void finished(); }
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean busy = new AtomicBoolean();
    private final LocalLlmRuntime runtime;
    private volatile LocalModelSession.Ticket active;
    private volatile boolean closed;
    private long sequence;
    LocalLlm(Context context) { runtime=LocalLlmRuntime.get(context); }
    static void requireMemory(Context context) throws IOException {
        if(!LocalLlmRuntime.memory(context).sufficient())throw new IOException("Сейчас мало свободной памяти для разговорной модели. Закройте тяжёлые приложения и повторите.");
    }
    boolean busy() { return busy.get(); }
    static String prompt(List<LocalChatRepository.Message> messages) {
        return prompt(messages,"");
    }
    static String prompt(List<LocalChatRepository.Message> messages,String responsePreferences) {
        String latest="";for(int i=messages.size()-1;i>=0;i--)if(messages.get(i).role().equals("user")){latest=messages.get(i).content();break;}
        String facts="";
        if(latest.matches("(?isu).*\\b(?:время|времени|час|часов|дата|дату|даты|сейчас|сегодня)\\b.*"))facts=" Системные дата и время телефона на момент этого запроса: "+java.time.ZonedDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd EEEE HH:mm XXX '['VV']'",new java.util.Locale("ru")))+". Это точнее старых ответов в истории. Не выдумывай другое текущее время или дату.";
        StringBuilder result = new StringBuilder("<|im_start|>system\nТы Уайли, русскоязычный помощник. Отвечай кратко и по-русски. Ты только пишешь текст: не утверждай, что выполнила действия на телефоне."+facts+responsePreferences+" /no_think<|im_end|>\n");
        List<LocalChatRepository.Message> selected = new ArrayList<>(); int used = 0;
        for (int i = messages.size() - 1; i >= 0 && selected.size() < 8; i--) {
            LocalChatRepository.Message message = messages.get(i); int size = message.content().length();
            if (used + size > 2400 && !selected.isEmpty()) break;
            selected.add(0, message); used += size;
        }
        while (!selected.isEmpty() && !selected.get(0).role().equals("user")) selected.remove(0);
        for (int index = 0; index < selected.size(); index++) {
            LocalChatRepository.Message message = selected.get(index);
            // Keep complete prior turns and the current request; an unanswered older request is not a second current prompt.
            if (message.role().equals("user") && index + 1 < selected.size() && selected.get(index + 1).role().equals("user")) continue;
            String content = message.content(); if (content.length() > 2400) content = content.substring(0, 2400);
            content = content.replace("<|", "< | ");
            result.append("<|im_start|>").append(message.role().equals("user") ? "user" : "assistant").append('\n').append(content).append("<|im_end|>\n");
        }
        return result.append("<|im_start|>assistant\n<think>\n\n</think>\n\n").toString();
    }
    void generate(Path model, String prompt, Listener listener) { generate(model,prompt,null,listener); }
    synchronized void generate(Path model,String prompt,String grammar,Listener listener) {
        if(closed || !busy.compareAndSet(false,true)) {
            main.post(()->{listener.error("Локальный запрос уже выполняется или экран закрыт");listener.finished();});return;
        }
        long ticket=++sequence;
        try {
            runtime.profileChanged();
            LocalModelSession.Ticket request=runtime.session.generate(LocalLlmRuntime.model(model),prompt,grammar,
                cold->post(ticket,()->listener.state(cold?"Загружаю модель телефона…":"Использую загруженную модель телефона…")),
                text->post(ticket,()->listener.partial(text)));
            active=request;
            request.result.whenComplete((answer,failure)->{
                post(ticket,()->{
                    try{if(failure!=null)listener.error(safeError(failure));else listener.done(answer.text(),answer.stopped()||request.cancelled.get());}
                    finally{synchronized(LocalLlm.this){if(active==request)active=null;busy.set(false);}listener.finished();}
                });
            });
        }catch(Exception|LinkageError|OutOfMemoryError failure){busy.set(false);post(ticket,()->{try{listener.error(safeError(failure));}finally{listener.finished();}});}
    }
    static String safeError(Throwable error) {
        while(error instanceof CompletionException || error instanceof ExecutionException){if(error.getCause()==null)break;error=error.getCause();}
        if(error instanceof OutOfMemoryError)return "Не хватило памяти для модели. Она выгружена; закройте тяжёлые приложения.";
        if(error instanceof LinkageError)return "Локальный движок недоступен для этой архитектуры Android";
        return error.getMessage()==null?"Не удалось получить локальный ответ":error.getMessage();
    }
    private void post(long ticket,Runnable callback){main.post(()->{synchronized(LocalLlm.this){if(!closed && sequence==ticket)callback.run();}});}
    synchronized void cancel(){LocalModelSession.Ticket request=active;if(request!=null)request.cancel();}
    synchronized void close(){if(closed)return;closed=true;cancel();active=null;busy.set(false);LocalLlmRuntime.releaseIfCreated("owner_closed");}
}
