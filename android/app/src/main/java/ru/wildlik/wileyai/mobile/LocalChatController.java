package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/** Serializes storage and marshals results to UI. Does not own an Activity. */
final class LocalChatController {
    interface Listener {
        void render(String title, String draft, List<LocalChatRepository.Message> messages, boolean hasOlder);
        void ready(boolean ready);
        void error(String message);
    }
    private final LocalChatRepository repository;
    private final SharedPreferences preferences;
    private final ExecutorService storage = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private Listener listener;
    private String selected = "";
    private volatile boolean closed;
    private int pending;
    private int messageLimit = 200;
    LocalChatController(Context context, Listener listener) {
        this.listener = listener; repository = new LocalChatRepository(context);
        preferences = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE);
        selected = preferences.getString("phone_chat", "");
    }
    private interface Work { void run() throws Exception; }
    private void work(Work work) {
        if (closed) return;
        pending++; listener.ready(false);
        storage.execute(() -> {
            try { work.run(); }
            catch (Exception e) { post(() -> listener.error("Не удалось сохранить или открыть историю телефона. Проверьте свободное место. Данные не удалены.")); }
            finally { post(() -> { pending--; listener.ready(pending == 0); }); }
        });
    }
    private void post(Runnable run) { main.post(() -> { if (!closed) run.run(); }); }
    private void persist(SharedPreferences.Editor edit) {
        // This method only runs on the storage executor; commit reports failed writes.
        if (!edit.commit()) throw new IllegalStateException("Не удалось сохранить настройки истории");
    }
    void load() { work(this::render); }
    private void render() {
        LocalChatRepository.Chat chat = selected.isEmpty() ? null : repository.chat(selected);
        if (chat == null) { selected = ""; preferences.edit().remove("phone_chat").apply(); }
        String title = chat == null ? "Новый чат" : chat.title();
        String draft = chat == null ? preferences.getString("phone_draft", "") : chat.draft();
        List<LocalChatRepository.Message> messages = chat == null ? new java.util.ArrayList<>() : repository.messages(selected, messageLimit + 1);
        boolean hasOlder = messages.size() > messageLimit;
        if (hasOlder) messages.remove(0);
        post(() -> listener.render(title, draft, messages, hasOlder));
    }
    void loadMore() { work(() -> { messageLimit += 200; render(); }); }
    void context(String id, Consumer<List<LocalChatRepository.Message>> result) { work(() -> { List<LocalChatRepository.Message> messages = repository.messages(id, 8); post(() -> result.accept(messages)); }); }
    void saveDraft(String draft) {
        work(() -> {
            if (selected.isEmpty()) persist(preferences.edit().putString("phone_draft", draft));
            else repository.draft(selected, draft);
        });
    }
    void choose(String id) {
        work(() -> {
            selected = id; messageLimit = 200;
            persist(preferences.edit().putString("phone_chat", id).putString("phone_draft", ""));
            render();
        });
    }
    void list(Consumer<List<LocalChatRepository.Chat>> result) {
        work(() -> { List<LocalChatRepository.Chat> chats = repository.chats(); post(() -> result.accept(chats)); });
    }
    void rename(String name) { work(() -> { if (!selected.isEmpty()) repository.rename(selected, name); render(); }); }
    void delete() {
        work(() -> {
            if (!selected.isEmpty()) repository.delete(selected);
            selected = ""; persist(preferences.edit().remove("phone_chat").remove("phone_draft")); render();
        });
    }
    void submit(String value, Consumer<String> saved) {
        work(() -> {
            selected = repository.submit(selected, value);
            persist(preferences.edit().putString("phone_chat", selected).remove("phone_draft"));
            String id = selected;
            render(); post(() -> saved.accept(id));
        });
    }
    void reply(String id, String message) {
        work(() -> { repository.append(id, "assistant", message); if (id.equals(selected)) render(); });
    }
    void close() { closed = true; listener = null; storage.execute(repository::close); storage.shutdown(); }
}
