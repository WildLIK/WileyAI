package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

/** One permission policy for setup, the settings page and feature entry points. */
final class RuntimeAccess {
    enum Item {
        MIC(Manifest.permission.RECORD_AUDIO, 26, "Микрофон", "Чтобы слышать ваши голосовые команды."),
        NOTICES(Manifest.permission.POST_NOTIFICATIONS, 33, "Уведомления", "Для напоминаний и кнопки остановки фонового микрофона."),
        HEADSET(Manifest.permission.BLUETOOTH_CONNECT, 31, "Bluetooth", "Чтобы слышать вас через подключённую гарнитуру.");

        final String permission, title, description;
        final int runtimeSince;

        Item(String permission, int runtimeSince, String title, String description) {
            this.permission = permission;
            this.runtimeSince = runtimeSince;
            this.title = title;
            this.description = description;
        }
    }

    private static final int REQUEST = 181;
    private final Activity activity;
    private Item pending;
    private Runnable continuation;

    RuntimeAccess(Activity activity) { this.activity = activity; }

    boolean granted(Item item) {
        if (item == Item.NOTICES && !activity.getSystemService(NotificationManager.class).areNotificationsEnabled()) return false;
        return Build.VERSION.SDK_INT < item.runtimeSince
                || activity.checkSelfPermission(item.permission) == PackageManager.PERMISSION_GRANTED;
    }

    private android.content.SharedPreferences preferences() {
        return activity.getSharedPreferences("runtime-permissions", Activity.MODE_PRIVATE);
    }

    String status(Item item) {
        if (granted(item)) return "Разрешено";
        if (preferences().getBoolean(item.permission, false)
                || activity.shouldShowRequestPermissionRationale(item.permission)) return "Отклонено";
        return item == Item.MIC ? "Требуется разрешение" : "Необязательно";
    }

    void request(Item item, MobileUi ui, Runnable afterGrant) {
        if (pending != null) return;
        if (granted(item)) { if (afterGrant != null) afterGrant.run(); return; }
        boolean rationale = activity.shouldShowRequestPermissionRationale(item.permission);
        boolean settingsOnly = Build.VERSION.SDK_INT < item.runtimeSince
                || activity.checkSelfPermission(item.permission) == PackageManager.PERMISSION_GRANTED
                || (!rationale && preferences().getBoolean(item.permission, false));
        if (settingsOnly) {
            SetupAction.show(ui, item.title, item.description + " Доступ можно изменить в настройках Android.",
                    "Настройки Android", () -> systemSettings(item, ui), null, null);
            return;
        }
        Runnable ask = () -> {
            pending = item;
            continuation = afterGrant;
            activity.requestPermissions(new String[]{item.permission}, REQUEST);
        };
        if (rationale) SetupAction.show(ui, item.title, item.description, "Запросить снова", ask, null, null);
        else ask.run();
    }

    boolean returned(int code, String[] permissions, int[] results, MobileUi ui, Runnable refresh) {
        if (code != REQUEST) return false;
        Item item = pending;
        Runnable done = continuation;
        pending = null;
        continuation = null;
        if (item == null && permissions.length > 0) {
            for (Item candidate : Item.values()) if (candidate.permission.equals(permissions[0])) item = candidate;
        }
        if (item != null && results.length > 0) {
            boolean allowed = results[0] == PackageManager.PERMISSION_GRANTED;
            preferences().edit().putBoolean(item.permission, !allowed
                    && !activity.shouldShowRequestPermissionRationale(item.permission)).apply();
            refresh.run();
            if (allowed && done != null) done.run();
            else if (!allowed) ui.dialog().setTitle(item.title).setMessage(item.description)
                    .setPositiveButton("Понятно", null).show();
        } else refresh.run();
        return true;
    }

    private void systemSettings(Item item, MobileUi ui) {
        Intent intent = item == Item.NOTICES
                ? new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, activity.getPackageName())
                : new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + activity.getPackageName()));
        try { activity.startActivity(intent); }
        catch (RuntimeException unavailable) {
            ui.dialog().setMessage("Откройте разрешения WileyAI в настройках Android.").setPositiveButton("Понятно", null).show();
        }
    }
}
