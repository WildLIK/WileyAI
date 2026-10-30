package ru.wildlik.wileyai.mobile;

import android.app.NotificationManager;
import android.content.*;
import android.media.*;
import android.media.session.*;
import android.os.*;
import android.view.KeyEvent;
import java.util.*;
import java.util.function.Consumer;

/** Routes only to chosen media apps; confirms state changes without repeated transport commands. */
final class PlayerControl {
    private static final Handler main=new Handler(Looper.getMainLooper());
    private static boolean changing;
    static ComponentName listener(Context context) { return new ComponentName(context,MediaAccessService.class); }
    static boolean permitted(Context context) {
        if(Build.VERSION.SDK_INT>=27)return ((NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE)).isNotificationListenerAccessGranted(listener(context));
        String enabled=android.provider.Settings.Secure.getString(context.getContentResolver(),"enabled_notification_listeners");
        if(enabled!=null)for(String name:enabled.split(":"))if(listener(context).equals(ComponentName.unflattenFromString(name)))return true;
        return false;
    }
    static List<MediaController> sessions(Context context) {
        if(!permitted(context)) return Collections.emptyList();
        Set<String> allowed=PlayerTargets.allowed(context); List<MediaController> result=new ArrayList<>();
        for(MediaController controller:((MediaSessionManager)context.getSystemService(Context.MEDIA_SESSION_SERVICE)).getActiveSessions(listener(context))) if(allowed.contains(controller.getPackageName())) result.add(controller);
        return result;
    }
    static void execute(Context context,PhoneCommands.Action action,Consumer<String> reply) {
        if(Looper.myLooper()!=Looper.getMainLooper()) { main.post(()->execute(context,action,reply)); return; }
        if(!permitted(context)) {
            if(action.target.isEmpty() && Arrays.asList("play","pause","next","previous").contains(action.value)) { legacy(context,action.value); reply.accept("Команда отправлена активному плееру Android. Для выбора плеера и проверки результата подключите «Музыка и YouTube» в Компонентах."); }
            else reply.accept("Подключите управление в «Компоненты → Музыка и YouTube». Android требует доступ к медиасессиям через настройки доступа к уведомлениям.");
            return;
        }
        try {
            List<MediaController> candidates=sessions(context); String pkg=action.target.isEmpty()?"":PlayerTargets.packageName(context,action.target);
            if(!action.target.isEmpty() && pkg.isEmpty()) { reply.accept("Сначала выберите приложение в «Музыка и YouTube»."); return; }
            if(!pkg.isEmpty()) candidates.removeIf(item->!item.getPackageName().equals(pkg));
            List<MediaController> playing=new ArrayList<>(); for(MediaController item:candidates) if(item.getPlaybackState()!=null && item.getPlaybackState().getState()==PlaybackState.STATE_PLAYING) playing.add(item);
            if(!playing.isEmpty()) candidates=playing;
            // More than one app requires a named target, never a guess based on list order.
            Set<String> packages=new HashSet<>(); for(MediaController item:candidates) packages.add(item.getPackageName());
            if(packages.size()>1) { reply.accept("Уточните плеер: «пауза в музыке» или «пауза в Ютубе»."); return; }
            if(candidates.isEmpty()) { if(action.target.equals("music")&&action.value.equals("play")&&!pkg.isEmpty()){MusicResume.connect(context,pkg,reply);return;}reply.accept("Активный плеер не найден. Откройте "+(pkg.isEmpty()?"музыку или YouTube":PlayerTargets.label(context,pkg))+" и запустите трек или видео."); return; }
            operate(context,candidates.get(0),action.value,reply);
        } catch(SecurityException revoked) { reply.accept("Доступ к медиасессиям отозван. Подключите его снова в «Музыка и YouTube»."); }
        catch(RuntimeException unavailable) { reply.accept("Не удалось связаться с плеером. Откройте его и повторите команду."); }
    }
    static void operate(Context context,MediaController controller,String verb,Consumer<String> reply) {
        if(verb.equals("status")) { reply.accept(describe(context,controller)); return; }
        if(changing) { reply.accept("Дождитесь результата предыдущей команды плееру."); return; }
        PlaybackState before=controller.getPlaybackState(); if(before==null) { reply.accept("Плеер не сообщил состояние и доступные команды."); return; }
        if(verb.equals("play") && before.getState()==PlaybackState.STATE_PLAYING || verb.equals("pause") && before.getState()==PlaybackState.STATE_PAUSED) { reply.accept(describe(context,controller)); return; }
        long required=verb.equals("play")?PlaybackState.ACTION_PLAY:verb.equals("pause")?PlaybackState.ACTION_PAUSE:verb.equals("next")?PlaybackState.ACTION_SKIP_TO_NEXT:verb.equals("previous")?PlaybackState.ACTION_SKIP_TO_PREVIOUS:PlaybackState.ACTION_SEEK_TO;
        boolean playPause=(verb.equals("play")||verb.equals("pause"))&&(before.getActions()&PlaybackState.ACTION_PLAY_PAUSE)!=0;
        if((before.getActions()&required)==0 && !playPause) { reply.accept(PlayerTargets.label(context,controller.getPackageName())+" сейчас не предоставляет эту команду Android. Доступно: "+capabilities(before)+"."); return; }
        long position=-1;
        if(verb.startsWith("seek:")||verb.startsWith("position:")) {
            MediaMetadata metadata=controller.getMetadata(); long duration=metadata==null?0:metadata.getLong(MediaMetadata.METADATA_KEY_DURATION);
            if(before.getPosition()<0 || duration<=0) { reply.accept("Плеер не сообщил длительность. Точная перемотка сейчас недоступна."); return; }
            long value=Long.parseLong(verb.substring(verb.indexOf(':')+1)); position=Math.max(0,Math.min(duration,verb.startsWith("seek:")?position(before)+value:value));
        }
        changing=true; Job job=new Job(context,controller,verb,before,position,reply); job.start();
    }
    static void resume(Context context,MediaController controller,Consumer<String> reply){
        PlaybackState state=controller.getPlaybackState();
        if(state!=null&&state.getState()!=PlaybackState.STATE_NONE){operate(context,controller,"play",reply);return;}
        if(changing){reply.accept("Дождитесь результата предыдущей команды плееру.");return;}
        // A newly connected browser may not publish state until the first explicit play request.
        changing=true;new Job(context,controller,"play",new PlaybackState.Builder().setState(PlaybackState.STATE_NONE,0,0).build(),-1,reply).start();
    }
    private static final class Job extends MediaController.Callback {
        final Context context; final MediaController controller; final String verb,beforeId; final PlaybackState before; final long target,began=SystemClock.elapsedRealtime(); final Consumer<String> reply;
        boolean done; final Runnable poll=this::check;
        Job(Context context,MediaController controller,String verb,PlaybackState before,long target,Consumer<String> reply) { this.context=context.getApplicationContext(); this.controller=controller; this.verb=verb; this.before=before; this.target=target; this.reply=reply; beforeId=identity(controller.getMetadata()); }
        void start() {
            try {
                controller.registerCallback(this,main); MediaController.TransportControls controls=controller.getTransportControls();
                if(verb.equals("play")) controls.play(); else if(verb.equals("pause")) controls.pause(); else if(verb.equals("next")) controls.skipToNext(); else if(verb.equals("previous")) controls.skipToPrevious(); else controls.seekTo(target);
                main.postDelayed(poll,150);
            } catch(RuntimeException failed) { finish("Плеер отклонил команду. Повторите после его открытия."); }
        }
        @Override public void onPlaybackStateChanged(PlaybackState state) { check(); }
        @Override public void onMetadataChanged(MediaMetadata metadata) { check(); }
        @Override public void onSessionDestroyed() { finish("Плеер завершил медиасессию. Результат команды не подтверждён."); }
        void check() {
            if(done) return; main.removeCallbacks(poll);
            try {
                PlaybackState state=controller.getPlaybackState();
                if(state!=null) {
                    if(state.getState()==PlaybackState.STATE_ERROR) { finish("Плеер сообщил ошибку воспроизведения."); return; }
                    String currentId=identity(controller.getMetadata());
                    boolean changed=!currentId.isEmpty()&&!currentId.equals(beforeId);
                    boolean restarted=verb.equals("previous")&&!currentId.isEmpty()&&currentId.equals(beforeId)&&before.getPosition()>3000&&state.getPosition()>=0&&state.getPosition()<=1500&&(state.getState()==PlaybackState.STATE_PLAYING||state.getState()==PlaybackState.STATE_PAUSED);
                    boolean confirmed=verb.equals("play")?state.getState()==PlaybackState.STATE_PLAYING:verb.equals("pause")?state.getState()==PlaybackState.STATE_PAUSED:
                        verb.equals("next")||verb.equals("previous")?changed||restarted:
                        (state.getLastPositionUpdateTime()>before.getLastPositionUpdateTime() || state.getPosition()!=before.getPosition()) && Math.abs(position(state)-(target+(state.getState()==PlaybackState.STATE_PLAYING?Math.round((SystemClock.elapsedRealtime()-began)*state.getPlaybackSpeed()):0)))<=2500;
                    if(confirmed) { finish((target>=0?"Позиция изменена. ":restarted?"Плеер вернул начало текущего трека. ":verb.equals("next")||verb.equals("previous")?"Трек или видео сменились. ":"")+describe(context,controller)); return; }
                }
                if(SystemClock.elapsedRealtime()-began>=3500) { finish("Команда передана в «"+PlayerTargets.label(context,controller.getPackageName())+"», но плеер не подтвердил изменение."); return; }
                main.postDelayed(poll,150);
            } catch(RuntimeException gone) { finish("Связь с плеером потеряна. Изменение не подтверждено."); }
        }
        void finish(String text) { if(done)return; done=true; changing=false; main.removeCallbacks(poll); try { controller.unregisterCallback(this); } catch(RuntimeException ignored) {} reply.accept(text); }
    }
    static String describe(Context context,MediaController controller) {
        PlaybackState state=controller.getPlaybackState(); MediaMetadata metadata=controller.getMetadata();
        String status=state==null?"состояние неизвестно":state.getState()==PlaybackState.STATE_PLAYING?"воспроизводится":state.getState()==PlaybackState.STATE_PAUSED?"на паузе":state.getState()==PlaybackState.STATE_BUFFERING||state.getState()==PlaybackState.STATE_CONNECTING?"загружается":"остановлено";
        String title=metadata==null?"":safe(metadata.getString(MediaMetadata.METADATA_KEY_TITLE)), artist=metadata==null?"":safe(metadata.getString(MediaMetadata.METADATA_KEY_ARTIST));
        long duration=metadata==null?0:metadata.getLong(MediaMetadata.METADATA_KEY_DURATION);
        return PlayerTargets.label(context,controller.getPackageName())+": "+status+(title.isEmpty()?"":" · "+title)+(artist.isEmpty()?"":" — "+artist)+(state==null||state.getPosition()<0?"":". "+clock(position(state))+(duration>0?" из "+clock(duration):""))+".";
    }
    static String capabilities(PlaybackState state) { List<String> names=new ArrayList<>(); if(state==null)return "нет данных"; long[] bits={PlaybackState.ACTION_PLAY|PlaybackState.ACTION_PLAY_PAUSE,PlaybackState.ACTION_PAUSE|PlaybackState.ACTION_PLAY_PAUSE,PlaybackState.ACTION_SKIP_TO_NEXT,PlaybackState.ACTION_SKIP_TO_PREVIOUS,PlaybackState.ACTION_SEEK_TO}; String[] labels={"продолжение","пауза","следующий","предыдущий","перемотка"}; for(int i=0;i<bits.length;i++) if((state.getActions()&bits[i])!=0)names.add(labels[i]); return names.isEmpty()?"нет команд":String.join(", ",names); }
    private static String identity(MediaMetadata metadata) { if(metadata==null)return ""; String id=metadata.getString(MediaMetadata.METADATA_KEY_MEDIA_ID); return id!=null&&!id.isEmpty()?id:safe(metadata.getString(MediaMetadata.METADATA_KEY_TITLE))+"|"+safe(metadata.getString(MediaMetadata.METADATA_KEY_ARTIST)); }
    private static String safe(String text) { if(text==null)return ""; String clean=text.replaceAll("[\\p{Cntrl}]"," ").trim(); return clean.substring(0,Math.min(120,clean.length())); }
    private static String clock(long ms) { long seconds=Math.max(0,ms)/1000; return seconds>=3600?String.format(Locale.ROOT,"%d:%02d:%02d",seconds/3600,seconds/60%60,seconds%60):String.format(Locale.ROOT,"%d:%02d",seconds/60,seconds%60); }
    private static long position(PlaybackState state) { return Math.max(0,state.getPosition()+(state.getState()==PlaybackState.STATE_PLAYING?Math.round(Math.max(0,SystemClock.elapsedRealtime()-state.getLastPositionUpdateTime())*state.getPlaybackSpeed()):0)); }
    private static void legacy(Context context,String verb) { AudioManager audio=(AudioManager)context.getSystemService(Context.AUDIO_SERVICE); int key=verb.equals("play")?KeyEvent.KEYCODE_MEDIA_PLAY:verb.equals("pause")?KeyEvent.KEYCODE_MEDIA_PAUSE:verb.equals("next")?KeyEvent.KEYCODE_MEDIA_NEXT:KeyEvent.KEYCODE_MEDIA_PREVIOUS; audio.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN,key)); audio.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_UP,key)); }
    private PlayerControl() {}
}
