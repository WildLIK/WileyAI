package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import java.util.concurrent.Executors;

/** Explicit app-owned alarms and system boot only; no exported command surface. */
public final class ReminderReceiver extends BroadcastReceiver {
    public void onReceive(Context context,Intent intent){PendingResult pending=goAsync();var worker=Executors.newSingleThreadExecutor();worker.execute(()->{try(ToolsData data=new ToolsData(context)){
        if(Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())){data.restore(context);return;}
        String id=intent.getStringExtra("id");if(id==null||!id.matches("[a-f0-9-]{36}"))return;
        try(Cursor cursor=data.getReadableDatabase().rawQuery("SELECT text,delivered FROM reminders WHERE id=?",new String[]{id})){
            if(!cursor.moveToFirst()||cursor.getInt(1)!=0)return;
            NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);if(!manager.areNotificationsEnabled())return;
            manager.createNotificationChannel(new NotificationChannel("reminders","Напоминания WileyAI",NotificationManager.IMPORTANCE_DEFAULT));
            PendingIntent open=PendingIntent.getActivity(context,0,new Intent(context,MainActivity.class).setAction("wiley.brain"),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
            manager.notify(id,1,new Notification.Builder(context,"reminders").setSmallIcon(android.R.drawable.ic_popup_reminder).setContentTitle("Напоминание WileyAI").setContentText(cursor.getString(0)).setContentIntent(open).setAutoCancel(true).build());
            ContentValues row=new ContentValues();row.put("delivered",1);data.getWritableDatabase().update("reminders",row,"id=?",new String[]{id});
        }
    }catch(RuntimeException ignored){/* No personal text in logs. Record remains available in the local list. */}finally{pending.finish();worker.shutdown();}});}
}
