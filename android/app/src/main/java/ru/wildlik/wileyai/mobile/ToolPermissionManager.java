package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;

/** Every step is checked at execution time; model-generated permissions are never accepted. */
final class ToolPermissionManager {
    static String denied(Context context,AndroidTools.Call call){
        if(((KeyguardManager)context.getSystemService(Context.KEYGUARD_SERVICE)).isDeviceLocked())return "Разблокируйте телефон для выполнения плана модели.";
        if(call.tool().startsWith("media_")&&!call.tool().equals("media_set_volume")&&!call.tool().equals("media_search")&&!PlayerControl.permitted(context))return "Для медиасессий включите доступ в «Компоненты → Музыка и YouTube».";
        if(call.tool().equals("get_foreground_app")){
            AppOpsManager ops=(AppOpsManager)context.getSystemService(Context.APP_OPS_SERVICE);
            if(ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,android.os.Process.myUid(),context.getPackageName())!=AppOpsManager.MODE_ALLOWED)return "Нужен выбранный вами доступ к статистике использования в настройках Android. Он не включается автоматически.";
        }
        if(call.tool().equals("create_reminder")&&((Build.VERSION.SDK_INT>=33&&context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)||!((NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE)).areNotificationsEnabled()))return "Для напоминаний разрешите уведомления WileyAI в настройках Android.";
        return "";
    }
    private ToolPermissionManager(){}
}
