package ru.wildlik.wileyai.mobile;

import android.app.SearchManager;
import android.content.*;
import android.content.pm.*;
import android.net.Uri;
import android.provider.MediaStore;
import java.util.function.Consumer;

/** Addressed Android intents; public YouTube results can be selected before launching a watch URL. */
final class MediaNavigation {
    static void execute(Context context,PhoneCommands.Action action,Consumer<Intent> launch,Consumer<String> reply) {
        execute(context,action,launch,reply,videos->{
            if(!(context instanceof android.app.Activity activity)||activity.isFinishing()||activity.isDestroyed())return;
            new MobileUi(activity,new SettingsRepository(context).theme()).dialog().setTitle("Какое видео включить?")
                .setItems(videos.stream().map(video->video.title()+"\n"+video.channel()).toArray(String[]::new),(d,index)->play(context,videos.get(index),launch,reply)).setNegativeButton("Отмена",(d,w)->reply.accept("Воспроизведение отменено.")).show();
        });
    }
    static void execute(Context context,PhoneCommands.Action action,Consumer<Intent> launch,Consumer<String> reply,Consumer<java.util.List<YoutubeSearch.Video>> choose) {
        if(action.target.equals("youtube")&&action.kind.equals("media_play_search")&&!action.value.startsWith("https://")){
            YoutubeSearch.find(action.value,videos->{
                if(videos.isEmpty()){search(context,action,launch,reply);return;}
                if(context.getSharedPreferences("wiley-mobile",0).getBoolean("youtube_first_result",false))play(context,videos.get(0),launch,reply);else choose.accept(videos);
            });return;
        }
        search(context,action,launch,reply);
    }
    static void play(Context context,YoutubeSearch.Video video,Consumer<Intent> launch,Consumer<String> reply){
        if(!video.id().matches("[A-Za-z0-9_-]{11}")){reply.accept("Некорректный адрес видео.");return;}
        String pkg=PlayerTargets.packageName(context,"youtube");if(pkg.isEmpty()){reply.accept("Выберите YouTube в настройках плееров.");return;}
        try{
            Intent intent=new Intent(Intent.ACTION_VIEW,Uri.parse("https://www.youtube.com/watch?v="+video.id())).setPackage(pkg);
            ResolveInfo resolved=context.getPackageManager().resolveActivity(intent,0);
            if(resolved==null||resolved.activityInfo==null||!resolved.activityInfo.exported||!resolved.activityInfo.enabled){reply.accept("Выбранный YouTube не открывает ссылки на видео.");return;}
            intent.setComponent(new ComponentName(resolved.activityInfo.packageName,resolved.activityInfo.name));launch.accept(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            reply.accept("Открываю видео «"+video.title()+"» в YouTube.");
        }catch(RuntimeException unavailable){reply.accept("Не удалось открыть видео. Проверьте YouTube и повторите команду.");}
    }
    private static void search(Context context,PhoneCommands.Action action,Consumer<Intent> launch,Consumer<String> reply) {
        String pkg=PlayerTargets.packageName(context,action.target);
        if(pkg.isEmpty()) { reply.accept("Выберите приложение в «Компоненты → Музыка и YouTube»."); return; }
        try {
            Intent intent;
            if(action.target.equals("youtube") && action.value.matches("(?i)^https://(?:www\\.|m\\.)?(?:youtube\\.com|youtu\\.be)/[^\\s]+$")) intent=new Intent(Intent.ACTION_VIEW,Uri.parse(action.value));
            else if(action.kind.equals("media_play_search")) intent=new Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH).putExtra(SearchManager.QUERY,action.value).putExtra(MediaStore.EXTRA_MEDIA_FOCUS,action.target.equals("music")?"vnd.android.cursor.item/audio":"video/*");
            else if(action.target.equals("youtube")) intent=new Intent(Intent.ACTION_SEARCH).putExtra(SearchManager.QUERY,action.value);
            else if(pkg.equals("ru.mts.music.android")) intent=new Intent(Intent.ACTION_VIEW,Uri.parse("https://music.mts.ru/search").buildUpon().appendQueryParameter("text",action.value).build());
            else intent=new Intent(Intent.ACTION_SEARCH).putExtra(SearchManager.QUERY,action.value);
            intent.setPackage(pkg); ResolveInfo resolved=context.getPackageManager().resolveActivity(intent,0);
            if(resolved==null && action.kind.equals("media_play_search")) {
                intent=action.target.equals("youtube")?new Intent(Intent.ACTION_SEARCH).putExtra(SearchManager.QUERY,action.value):pkg.equals("ru.mts.music.android")?new Intent(Intent.ACTION_VIEW,Uri.parse("https://music.mts.ru/search").buildUpon().appendQueryParameter("text",action.value).build()):new Intent(Intent.ACTION_SEARCH).putExtra(SearchManager.QUERY,action.value);
                intent.setPackage(pkg); resolved=context.getPackageManager().resolveActivity(intent,0);
            }
            if(resolved==null || resolved.activityInfo==null || !resolved.activityInfo.exported || !resolved.activityInfo.enabled) { reply.accept("Выбранное приложение не предоставляет поиск Android. Откройте его и воспользуйтесь поиском внутри."); return; }
            intent.setComponent(new ComponentName(resolved.activityInfo.packageName,resolved.activityInfo.name));
            launch.accept(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            reply.accept((MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH.equals(intent.getAction())?"Запрос на воспроизведение передан в «":"Поиск открыт в «")+PlayerTargets.label(context,pkg)+"»: "+action.value+". Результат выбирает приложение.");
        } catch(RuntimeException unavailable) { reply.accept("Не удалось открыть поиск в выбранном плеере. Проверьте приложение и подключение к интернету."); }
    }
    private MediaNavigation() {}
}
