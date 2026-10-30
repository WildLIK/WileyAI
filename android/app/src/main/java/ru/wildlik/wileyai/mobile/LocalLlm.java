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

/** CPU-only chat; no network, tools, shell, or action dispatcher. Releases RAM after each answer. */
final class LocalLlm {
    interface Listener { void state(String text); void partial(String text); void done(String text, boolean stopped); void error(String text); void finished(); }
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean busy = new AtomicBoolean(), cancelled = new AtomicBoolean();
    private final Object lock = new Object(); private long handle; private volatile boolean closed;
    private final Context context;
    LocalLlm(Context context) { this.context = context.getApplicationContext(); }
    static void requireMemory(Context context) throws IOException { android.app.ActivityManager.MemoryInfo memory = new android.app.ActivityManager.MemoryInfo(); ((android.app.ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(memory); if (memory.lowMemory || memory.availMem < 768L * 1048576) throw new IOException("Сейчас мало свободной памяти для разговорной модели. Закройте тяжёлые приложения и повторите."); }
    boolean busy() { return busy.get(); }
    static String prompt(List<LocalChatRepository.Message> messages) {
        String latest="";for(int i=messages.size()-1;i>=0;i--)if(messages.get(i).role().equals("user")){latest=messages.get(i).content();break;}
        String facts="";
        if(latest.matches("(?isu).*\\b(?:время|времени|час|часов|дата|дату|даты|сейчас|сегодня)\\b.*"))facts=" Системные дата и время телефона на момент этого запроса: "+java.time.ZonedDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd EEEE HH:mm XXX '['VV']'",new java.util.Locale("ru")))+". Это точнее старых ответов в истории. Не выдумывай другое текущее время или дату.";
        StringBuilder result = new StringBuilder("<|im_start|>system\nТы Уайли, русскоязычный помощник. Отвечай кратко и по-русски. Ты только пишешь текст: не утверждай, что выполнила действия на телефоне."+facts+" /no_think<|im_end|>\n");
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
    void generate(Path model, String prompt, Listener listener) {
        generate(model,prompt,null,listener);
    }
    void generate(Path model,String prompt,String grammar,Listener listener){
        if (closed || !busy.compareAndSet(false, true)) return; cancelled.set(false);
        worker.execute(() -> {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(); String answer = "";
            try {
                requireMemory(context);
                post(() -> listener.state("Загружаю модель телефона…"));
                long session = LocalLlmNative.load(model.toString());
                synchronized (lock) { handle = session; if (cancelled.get()) LocalLlmNative.cancel(handle); }
                if(grammar!=null)LocalLlmNative.grammar(session,grammar.getBytes(StandardCharsets.UTF_8));
                if (!cancelled.get()) {
                    LocalLlmNative.begin(session, prompt.getBytes(StandardCharsets.UTF_8)); post(() -> listener.state("Отвечаю на телефоне…"));
                    long updated = 0, began = SystemClock.elapsedRealtime(); boolean ended = false;
                    for (int i = 0; i < 256 && !cancelled.get() && SystemClock.elapsedRealtime() - began < 90000; i++) {
                        byte[] piece = LocalLlmNative.next(session); if (piece == null) { ended = true; break; } bytes.write(piece);
                        ByteBuffer input = ByteBuffer.wrap(bytes.toByteArray()); CharBuffer output = CharBuffer.allocate(bytes.size());
                        StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPLACE).decode(input, output, false); output.flip(); answer = output.toString();
                        if (SystemClock.elapsedRealtime() - updated > 80) { updated = SystemClock.elapsedRealtime(); String shown = answer; post(() -> listener.partial(shown)); }
                    }
                    if (!ended && !cancelled.get()) answer += "\n\n[Достигнут лимит ответа для этой модели]";
                }
                String complete = answer.trim(); boolean stopped = cancelled.get(); post(() -> listener.done(complete, stopped));
            } catch (OutOfMemoryError error) { post(() -> listener.error("Не хватило памяти для модели. Она выгружена; попробуйте закрыть тяжёлые приложения.")); }
            catch (LinkageError error) { post(() -> listener.error("Локальный движок недоступен для этой архитектуры Android")); }
            catch (Exception error) { String message = cancelled.get() ? "Ответ остановлен" : error.getMessage(); post(() -> listener.error(message == null ? "Не удалось получить локальный ответ" : message)); }
            finally {
                synchronized (lock) { if (handle != 0) { LocalLlmNative.close(handle); handle = 0; } }
                busy.set(false); post(listener::finished);
            }
        });
    }
    private void post(Runnable callback) { main.post(() -> { if (!closed) callback.run(); }); }
    void cancel() { cancelled.set(true); synchronized (lock) { if (handle != 0) LocalLlmNative.cancel(handle); } }
    void close() { closed = true; cancel(); worker.shutdown(); }
}
