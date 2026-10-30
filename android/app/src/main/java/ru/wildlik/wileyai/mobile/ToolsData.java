package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import java.util.*;

/** App-owned notes and inexact reminders; no access to the user's calendar or contacts. */
final class ToolsData extends SQLiteOpenHelper {
    ToolsData(Context context){super(context.getApplicationContext(),"assistant-tools.db",null,1);}
    public void onCreate(SQLiteDatabase db){db.execSQL("CREATE TABLE notes(id TEXT PRIMARY KEY, text TEXT NOT NULL, created INTEGER NOT NULL)");db.execSQL("CREATE TABLE reminders(id TEXT PRIMARY KEY,text TEXT NOT NULL,due INTEGER NOT NULL,delivered INTEGER NOT NULL DEFAULT 0)");}
    public void onUpgrade(SQLiteDatabase db,int old,int newer){throw new IllegalStateException("Неизвестная версия данных инструментов");}
    String note(String text){String id=UUID.randomUUID().toString();ContentValues row=new ContentValues();row.put("id",id);row.put("text",text);row.put("created",System.currentTimeMillis());getWritableDatabase().insertOrThrow("notes",null,row);return id;}
    String reminder(Context context,String text,long due){String id=UUID.randomUUID().toString();ContentValues row=new ContentValues();row.put("id",id);row.put("text",text);row.put("due",due);getWritableDatabase().insertOrThrow("reminders",null,row);try{schedule(context,id,due);}catch(RuntimeException error){getWritableDatabase().delete("reminders","id=?",new String[]{id});throw error;}return id;}
    List<Map<String,Object>> reminders(){List<Map<String,Object>> result=new ArrayList<>();try(Cursor cursor=getReadableDatabase().rawQuery("SELECT id,text,due,delivered FROM reminders ORDER BY due DESC LIMIT 20",null)){while(cursor.moveToNext())result.add(Map.of("id",cursor.getString(0),"text",cursor.getString(1),"due",cursor.getLong(2),"delivered",cursor.getInt(3)!=0));}return result;}
    static void schedule(Context context,String id,long due){Intent intent=new Intent(context,ReminderReceiver.class).setAction("wiley.reminder").setData(android.net.Uri.parse("wiley-reminder://local/"+id)).putExtra("id",id);PendingIntent pending=PendingIntent.getBroadcast(context,0,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);((AlarmManager)context.getSystemService(Context.ALARM_SERVICE)).setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,due,pending);}
    void restore(Context context){try(Cursor cursor=getReadableDatabase().rawQuery("SELECT id,due FROM reminders WHERE delivered=0",null)){while(cursor.moveToNext())schedule(context,cursor.getString(0),Math.max(System.currentTimeMillis()+5000,cursor.getLong(1)));}}
}
