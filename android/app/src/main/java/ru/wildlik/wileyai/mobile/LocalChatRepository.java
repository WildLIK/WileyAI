package ru.wildlik.wileyai.mobile;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** Phone-only history. Call on the single storage executor, never the UI thread. */
final class LocalChatRepository extends SQLiteOpenHelper {
    static final String CHATS = "CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT NOT NULL, draft TEXT NOT NULL DEFAULT '', updated INTEGER NOT NULL)";
    static final String MESSAGES = "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created INTEGER NOT NULL)";
    static final String INDEX = "CREATE INDEX messages_chat ON messages(chat_id, id)";
    static final String RECOVERIES = "CREATE TABLE gateway_recoveries (run_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE)";
    record Chat(String id, String title, String draft) {}
    record Message(String role, String content) {}

    LocalChatRepository(Context context) { this(context, "phone-chats.db"); }
    LocalChatRepository(Context context, String name) { super(context.getApplicationContext(), name, null, 2); }
    @Override public void onConfigure(SQLiteDatabase db) { db.setForeignKeyConstraintsEnabled(true); }
    @Override public void onCreate(SQLiteDatabase db) { db.execSQL(CHATS); db.execSQL(MESSAGES); db.execSQL(INDEX); db.execSQL(RECOVERIES); }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if(oldVersion==1&&newVersion==2){db.execSQL(RECOVERIES);return;}
        throw new IllegalStateException("Для этой версии истории нужна явная миграция. Данные сохранены.");
    }
    void recover(String chatId,String runId,String content){
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{
            if(chat(chatId)==null)return;
            ContentValues values=new ContentValues();values.put("run_id",runId);values.put("chat_id",chatId);
            if(db.insertWithOnConflict("gateway_recoveries",null,values,SQLiteDatabase.CONFLICT_IGNORE)!=-1)append(chatId,"assistant",content);
            db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    List<Chat> chats() {
        List<Chat> result = new ArrayList<>();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT id,title,draft FROM chats ORDER BY updated DESC, rowid DESC", null)) {
            while (c.moveToNext()) result.add(new Chat(c.getString(0), c.getString(1), c.getString(2)));
        }
        return result;
    }
    Chat chat(String id) {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT id,title,draft FROM chats WHERE id=?", new String[]{id})) {
            return c.moveToFirst() ? new Chat(c.getString(0), c.getString(1), c.getString(2)) : null;
        }
    }
    String create(String title) {
        String id = UUID.randomUUID().toString();
        ContentValues values = new ContentValues(); values.put("id", id); values.put("title", title); values.put("updated", System.currentTimeMillis());
        getWritableDatabase().insertOrThrow("chats", null, values); return id;
    }
    List<Message> messages(String id) {
        return messages(id, Integer.MAX_VALUE);
    }
    List<Message> messages(String id, int limit) {
        List<Message> result = new ArrayList<>();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT role,content FROM (SELECT id,role,content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?) ORDER BY id", new String[]{id, Integer.toString(limit)})) {
            while (c.moveToNext()) result.add(new Message(c.getString(0), c.getString(1)));
        }
        return result;
    }
    void append(String id, String role, String content) {
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            ContentValues values = new ContentValues(); values.put("chat_id", id); values.put("role", role); values.put("content", content); values.put("created", System.currentTimeMillis());
            db.insertOrThrow("messages", null, values);
            ContentValues update = new ContentValues(); update.put("updated", System.currentTimeMillis());
            if (db.update("chats", update, "id=?", new String[]{id}) != 1) throw new IllegalStateException("Чат не найден");
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    String submit(String existing, String value) {
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            // A user can delete the assistant's chat while its service is still alive.
            // Recreate only the missing chat, without discarding any remaining history.
            String id = existing.isEmpty() || chat(existing) == null ? create(value.length() > 48 ? value.substring(0, 48) + "…" : value) : existing;
            append(id, "user", value); draft(id, "");
            db.setTransactionSuccessful(); return id;
        } finally { db.endTransaction(); }
    }
    void draft(String id, String text) { update(id, "draft", text); }
    void rename(String id, String title) {
        if (title.trim().isEmpty()) throw new IllegalArgumentException("Введите название чата");
        update(id, "title", title.trim());
    }
    private void update(String id, String column, String value) {
        ContentValues values = new ContentValues(); values.put(column, value);
        if (getWritableDatabase().update("chats", values, "id=?", new String[]{id}) != 1) throw new IllegalStateException("Чат не найден");
    }
    void delete(String id) { getWritableDatabase().delete("chats", "id=?", new String[]{id}); }
}
