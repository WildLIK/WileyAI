package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.media.AudioManager;
import android.view.KeyEvent;
import java.util.Locale;

/** Bounded Android audio/device queries shared by Activity and assistant service. */
final class PhoneActionCore {
    static void execute(Context context, PhoneCommands.Action action, java.util.function.Consumer<String> reply) {
        try {
            if (action.kind.equals("info")) {
                if (action.value.equals("time")) reply.accept("Сейчас " + java.time.ZonedDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm", new Locale("ru"))) + " по времени телефона.");
                else if (action.value.equals("date")) reply.accept("Сегодня " + java.time.LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("EEEE, d MMMM yyyy", new Locale("ru"))) + ".");
                else { android.os.BatteryManager battery = (android.os.BatteryManager)context.getSystemService(Context.BATTERY_SERVICE); int percent = battery.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY); reply.accept(percent >= 0 && percent <= 100 ? "Заряд батареи: " + percent + "%." : "Android не сообщил уровень заряда батареи."); }
                return;
            }
            if (action.kind.equals("volume")) {
                AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
                int max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                int current = audio.getStreamVolume(AudioManager.STREAM_MUSIC);
                android.content.SharedPreferences saved = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE);
                if (action.value.equals("0") && current > 0) saved.edit().putInt("music_before_mute", current).apply();
                int value = action.value.equals("up") ? Math.min(max, current + Math.max(1, Math.round(max * .1f))) :
                        action.value.equals("down") ? Math.max(0, current - Math.max(1, Math.round(max * .1f))) :
                        action.value.startsWith("up:") ? Math.min(max, current + Math.round(max * Integer.parseInt(action.value.substring(3)) / 100f)) :
                        action.value.startsWith("down:") ? Math.max(0, current - Math.round(max * Integer.parseInt(action.value.substring(5)) / 100f)) :
                        action.value.equals("restore") ? Math.min(max, saved.getInt("music_before_mute", Math.max(1, Math.round(max * .25f)))) :
                        action.value.equals("status") ? current : Math.round(max * Integer.parseInt(action.value) / 100f);
                if (audio.isVolumeFixed() && !action.value.equals("status")) { reply.accept("Android зафиксировал громкость текущего устройства вывода. Измените её на подключённом устройстве."); return; }
                if (!action.value.equals("status")) audio.setStreamVolume(AudioManager.STREAM_MUSIC, value, AudioManager.FLAG_SHOW_UI);
                int actual = audio.getStreamVolume(AudioManager.STREAM_MUSIC);
                if (actual != value && !action.value.equals("status")) { reply.accept("Android не применил запрошенную громкость. Сейчас: " + Math.round(actual * 100f / Math.max(1, max)) + "%. Проверьте ограничение громкости и устройство вывода."); return; }
                reply.accept(volumeDescription(actual,max)); return;
            }
            if (action.kind.equals("media")) { PlayerControl.execute(context,action,reply); return; }
            reply.accept("Эта команда не поддерживается");
        } catch (Exception e) { reply.accept("Не удалось выполнить команду на телефоне: " + (e.getMessage() == null ? "приложение недоступно" : e.getMessage())); }
    }
    static String volumeDescription(int actual,int max){
        int percent=Math.round(actual*100f/Math.max(1,max));
        boolean samsung=android.os.Build.MANUFACTURER.equalsIgnoreCase("samsung")&&max==15;
        return "Громкость музыки на телефоне: "+(samsung?"около "+actual*10+" из 150 по шкале Samsung ("+percent+"% максимума)":percent+"%")+".";
    }
    private PhoneActionCore() {}
}
