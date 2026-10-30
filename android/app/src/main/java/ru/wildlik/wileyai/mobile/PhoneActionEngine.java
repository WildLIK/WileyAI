package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.ResolveInfo;
import android.content.Context;
import android.media.AudioManager;
import android.net.Uri;
import android.view.KeyEvent;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Bounded Android actions. No network client or language model dependency. */
final class PhoneActionEngine {
    private final Activity activity;
    private final java.util.function.Consumer<String> reply;
    private final AppCatalog apps;
    private final java.util.function.BooleanSupplier foreground;
    PhoneActionEngine(Activity activity, java.util.function.Consumer<String> reply, AppCatalog apps, java.util.function.BooleanSupplier foreground) {
        this.activity = activity; this.reply = reply; this.apps = apps; this.foreground = foreground;
    }
    void execute(PhoneCommands.Action action) {
        if(action.kind.equals("media_search") || action.kind.equals("media_play_search")) {
            if(!foreground.getAsBoolean()) { reply.accept("Открытие поиска отменено: вернитесь в WileyAI."); return; }
            MediaNavigation.execute(activity,action,intent->{if(!foreground.getAsBoolean()||activity.isFinishing()||activity.isDestroyed())throw new IllegalStateException();activity.startActivity(intent);},text->{if(foreground.getAsBoolean())reply.accept(text);},videos->{
                if(!foreground.getAsBoolean()||activity.isFinishing()||activity.isDestroyed())return;
                new MobileUi(activity,new SettingsRepository(activity).theme()).dialog().setTitle("Какое видео включить?").setItems(videos.stream().map(video->video.title()+"\n"+video.channel()).toArray(String[]::new),(d,index)->{
                    if(!foreground.getAsBoolean())return;MediaNavigation.play(activity,videos.get(index),activity::startActivity,reply);
                }).setNegativeButton("Отмена",(d,w)->reply.accept("Воспроизведение отменено.")).show();
            });
        } else if (action.kind.equals("open")) openPhoneTarget(action.value);
        else PhoneActionCore.execute(activity, action, reply);
    }
    private void openPhoneTarget(String target) {
        apps.resolve(target, matches -> {
            if (!foreground.getAsBoolean()) { reply.accept("Запуск отменён: WileyAI больше не открыт на экране."); return; }
            try {
                if (!target.matches("(?i)^https?://.*") && !matches.isEmpty()) {
                    if (matches.size() == 1) { launchPhoneApp(matches.get(0)); return; }
                    String[] names = new String[matches.size()];
                    for (int i = 0; i < matches.size(); i++) names[i] = matches.get(i).label() + " (" + matches.get(i).packageName() + ")";
                    new MobileUi(activity, new SettingsRepository(activity).theme()).dialog().setTitle("Какое приложение открыть?")
                        .setItems(names, (dialog, index) -> launchPhoneApp(matches.get(index))).setNegativeButton("Отмена", (d, w) -> reply.accept("Запуск отменён")).show();
                    return;
                }
                String key = SpokenNames.app(target);
                if (key.equals("браузер")) {
                    activity.startActivity(Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_BROWSER));
                    reply.accept("Команда запуска браузера передана Android."); return;
                }
                String url = key.equals("youtube") ? "https://www.youtube.com" : key.equals("яндекс") ? "https://ya.ru" :
                    key.equals("гугл") || key.equals("google") ? "https://www.google.com" : key.equals("гитхаб") || key.equals("github") ? "https://github.com" : "";
                if (target.matches("(?i)^https?://[^\\s]+$")) url = target;
                else if (target.matches("(?i)^[a-z0-9-]+(?:\\.[a-z0-9-]+)+(?:/[^\\s]*)?$")) url = "https://" + target;
                if (!url.isEmpty()) {
                    Uri uri = Uri.parse(url);
                    if (!("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme())) || uri.getHost() == null || uri.getUserInfo() != null) throw new Exception("Допустимы только адреса HTTP и HTTPS");
                    activity.startActivity(new Intent(Intent.ACTION_VIEW, uri)); reply.accept("Команда открытия сайта передана Android. Для загрузки сайта может потребоваться интернет."); return;
                }
                List<AppRegistry.App> suggestions=AppRegistry.suggest(apps.entries(),target);
                if(!suggestions.isEmpty()){
                    new MobileUi(activity,new SettingsRepository(activity).theme()).dialog().setTitle("Похожее название — что открыть?")
                        .setItems(suggestions.stream().map(AppRegistry.App::label).toArray(String[]::new),(d,index)->launchPhoneApp(suggestions.get(index))).setNegativeButton("Отмена",null).show();return;
                }
                reply.accept("Приложение «" + target + "» не найдено в каталоге. Откройте «Команды → Мои приложения» и обновите список или задайте своё название для голоса.");
            } catch (Exception error) { reply.accept("Не удалось открыть приложение или сайт на телефоне. Проверьте доступность приложения и адрес."); }
        });
    }
    void launchPhoneApp(AppRegistry.App app) {
        if (!foreground.getAsBoolean() || activity.isDestroyed() || activity.isFinishing()) { reply.accept("Запуск отменён: вернитесь в WileyAI и повторите команду."); return; }
        try {
            android.content.ComponentName component = new android.content.ComponentName(app.packageName(), app.activity());
            android.content.pm.ActivityInfo actual = activity.getPackageManager().getActivityInfo(component, 0);
            if (!actual.enabled || !actual.exported || !actual.applicationInfo.enabled) throw new Exception("Приложение отключено");
            Intent intent = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setComponent(component)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            activity.startActivity(intent); reply.accept("Команда запуска «" + app.label() + "» передана Android.");
        } catch (Exception error) { apps.refresh(); reply.accept("Не удалось открыть приложение: возможно, оно удалено или отключено. Обновляю каталог."); }
    }
}
