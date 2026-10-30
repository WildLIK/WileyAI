package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.*;
import java.util.List;
import java.util.concurrent.*;
import java.util.function.*;

/** Separate assistant conversation in the existing SQLite history; never changes the open chat/draft. */
final class AssistantConversation {
    private final LocalChatRepository repository; private final android.content.SharedPreferences preferences;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(); private final Handler main = new Handler(Looper.getMainLooper()); private boolean closed;
    interface Submitted { void done(String id, List<LocalChatRepository.Message> messages); }
    AssistantConversation(Context context) { this(new LocalChatRepository(context), context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE)); }
    AssistantConversation(LocalChatRepository repository, android.content.SharedPreferences preferences) { this.repository = repository; this.preferences = preferences; }
    void submit(String text, Submitted callback, Consumer<String> error) {
        worker.execute(() -> { try { String id = repository.submit(preferences.getString("assistant_chat", ""), text); if (!preferences.edit().putString("assistant_chat", id).commit()) throw new IllegalStateException(); List<LocalChatRepository.Message> context = repository.messages(id, 8); main.post(() -> { if (!closed) callback.done(id, context); }); } catch (Exception failure) { android.util.Log.w("WileyHistory", "Assistant history write failed: " + failure.getClass().getSimpleName()); main.post(() -> { if (!closed) error.accept("История сейчас недоступна. Команды телефону продолжают работать; вопрос для чата можно повторить позже."); }); } });
    }
    void reply(String id, String text) { if (closed || id.isEmpty()) return; worker.execute(() -> { try { repository.append(id, "assistant", text); } catch (Exception ignored) {} }); }
    void close() { closed = true; worker.execute(repository::close); worker.shutdown(); }
}
