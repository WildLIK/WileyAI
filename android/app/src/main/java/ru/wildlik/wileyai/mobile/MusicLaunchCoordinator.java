package ru.wildlik.wileyai.mobile;

import android.app.SearchManager;
import android.content.*;
import android.content.pm.ResolveInfo;
import android.media.MediaMetadata;
import android.media.session.*;
import android.os.*;
import android.provider.MediaStore;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** Bounded, single-flight cold start; observes only the explicitly selected player. */
final class MusicLaunchCoordinator {
    private static final Handler main=new Handler(Looper.getMainLooper());
    private static volatile Job pending;
    static boolean busy(){return pending!=null;}
    static void start(Context context,String pkg,String request,Consumer<Intent> launch,BooleanSupplier active,PhoneActionReply reply){
        if(Looper.myLooper()!=Looper.getMainLooper()){main.post(()->start(context,pkg,request,launch,active,reply));return;}
        if(pending!=null){reply.accept("Дождитесь результата предыдущего запуска музыки.");return;}
        Job job=new Job(context,pkg,request,launch,active,reply);pending=job;job.start();
    }
    private static final class Job {
        final Context context;final String pkg,request;final Consumer<Intent> launch;final BooleanSupplier active;final PhoneActionReply reply;
        final MediaSessionManager manager;final long began=SystemClock.elapsedRealtime(),deadline=began+20000,catalogAt=began+6000;
        boolean done,dispatched,catalogStarted; Runnable cancelBrowser,cancelCatalog;MusicCatalogSelector.Selection selection;MediaController catalogController;MediaController.Callback catalogObserver;
        final Runnable poll=this::check; final Runnable watchdog=this::watch;final Runnable verify=this::verifyCatalog;
        final MediaSessionManager.OnActiveSessionsChangedListener listener=controllers->check();
        Job(Context context,String pkg,String request,Consumer<Intent> launch,BooleanSupplier active,PhoneActionReply reply){this.context=context;this.pkg=pkg;this.request=request;this.launch=launch;this.active=active;this.reply=reply;manager=(MediaSessionManager)context.getSystemService(Context.MEDIA_SESSION_SERVICE);}
        void start(){
            main.postDelayed(watchdog,200);
            try{
                if(launch==null){resumeService();return;}
                manager.addOnActiveSessionsChangedListener(listener,PlayerControl.listener(context),main);
                Intent intent=new Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH).setPackage(pkg).putExtra(SearchManager.QUERY,"").putExtra(MediaStore.EXTRA_MEDIA_FOCUS,"vnd.android.cursor.item/audio");
                ResolveInfo resolved=context.getPackageManager().resolveActivity(intent,0);
                if(resolved==null||resolved.activityInfo==null||!resolved.activityInfo.exported||!resolved.activityInfo.enabled){
                    intent=context.getPackageManager().getLaunchIntentForPackage(pkg);
                    if(intent==null){resumeService();return;}
                } else intent.setComponent(new ComponentName(resolved.activityInfo.packageName,resolved.activityInfo.name));
                if(!active.getAsBoolean()){finish(null);return;}
                launch.accept(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                check();
            }catch(SecurityException e){finish("Android не разрешил доступ к плееру или медиасессиям.");}
            catch(RuntimeException e){finish("Не удалось открыть музыкальный плеер. Разблокируйте телефон и повторите команду.");}
        }
        void resumeService(){
            if(!active.getAsBoolean()){finish(null);return;}
            catalogStarted=true;startCatalog(true);
        }
        void resumeLegacy(){
            if(!active.getAsBoolean()){finish(null);return;}
            dispatched=true;try{manager.removeOnActiveSessionsChangedListener(listener);}catch(RuntimeException ignored){}
            Runnable cancel=MusicResume.connect(context,pkg,request,()->!done&&active.getAsBoolean()&&SystemClock.elapsedRealtime()<deadline,(display,spoken)->complete(display,spoken));
            cancelBrowser=cancel;if(done)cancel.run();
        }
        void startCatalog(boolean allowLegacy){
            Runnable cancel=MusicCatalogSelector.find(context,pkg,selected->{if(done||dispatched)return;if(selected==null){if(allowLegacy){resumeLegacy();return;}finish("Плеер не предоставил однозначный музыкальный микс. Выберите музыку в приложении.");return;}selection=selected;check();});
            cancelCatalog=cancel;if(done)cancel.run();
        }
        void watch(){
            if(done)return;
            if(!active.getAsBoolean()){if(dispatched)PlayerControl.cancelPending();finish(null);return;}
            if(SystemClock.elapsedRealtime()>=deadline){if(dispatched)PlayerControl.cancelPending();finish(dispatched?"Плеер не подтвердил запуск вовремя. Повторная команда не отправлялась.":"Плеер открылся, но не предоставил композицию для возобновления. Выберите музыку в приложении.");return;}
            main.postDelayed(watchdog,200);
        }
        void check(){
            if(done||dispatched)return;
            main.removeCallbacks(poll);
            if(!active.getAsBoolean()){finish(null);return;}
            try{
                List<MediaController> matches=new ArrayList<>();
                for(MediaController c:PlayerControl.sessions(context))if(pkg.equals(c.getPackageName()))matches.add(c);
                if(matches.size()>1){finish("У плеера несколько медиасессий. Выберите музыку в приложении.");return;}
                if(matches.size()==1){
                    MediaController c=matches.get(0);PlaybackState state=c.getPlaybackState();MediaMetadata meta=c.getMetadata();
                    if(state!=null && state.getState()==PlaybackState.STATE_PLAYING){complete(PlayerControl.describe(context,c),"Музыка уже играет.");return;}
                    boolean hasTrack=meta!=null && (nonempty(meta.getString(MediaMetadata.METADATA_KEY_MEDIA_ID))||nonempty(meta.getString(MediaMetadata.METADATA_KEY_TITLE)));
                    if(state!=null && state.getState()==PlaybackState.STATE_ERROR){finish("Плеер сообщил ошибку воспроизведения.");return;}
                    boolean ready=state!=null&&(state.getState()==PlaybackState.STATE_PAUSED||state.getState()==PlaybackState.STATE_STOPPED);
                    if(ready && hasTrack && (state.getActions()&(PlaybackState.ACTION_PLAY|PlaybackState.ACTION_PLAY_PAUSE))!=0){
                        dispatched=true; removeListener();
                        PlayerControl.operate(context,c,"play",request,(display,spoken)->complete(display,spoken));return;
                    }
                }
                if(selection!=null){playCatalog();if(done||dispatched)return;}
                if(!catalogStarted&&SystemClock.elapsedRealtime()>=catalogAt){
                    catalogStarted=true;startCatalog(false);if(done)return;
                }
                if(SystemClock.elapsedRealtime()>=deadline){finish("Плеер открылся, но не предоставил композицию для возобновления. Выберите музыку в приложении.");return;}
                main.postDelayed(poll,200);
            }catch(SecurityException e){finish("Доступ к медиасессиям отозван; запуск не подтверждён.");}
            catch(RuntimeException e){finish("Не удалось получить состояние плеера; запуск не подтверждён.");}
        }
        void playCatalog(){
            MediaController c=selection.controller;PlaybackState state=c.getPlaybackState();
            if(state!=null&&state.getState()==PlaybackState.STATE_PLAYING){complete(PlayerControl.describe(context,c),"Музыка уже играет.");return;}
            if(state!=null&&(state.getState()==PlaybackState.STATE_BUFFERING||state.getState()==PlaybackState.STATE_CONNECTING))return;
            if(state!=null&&state.getState()==PlaybackState.STATE_ERROR){finish("Плеер сообщил ошибку воспроизведения.");return;}
            MediaMetadata existing=c.getMetadata();boolean hasTrack=existing!=null&&(nonempty(existing.getString(MediaMetadata.METADATA_KEY_MEDIA_ID))||nonempty(existing.getString(MediaMetadata.METADATA_KEY_TITLE)));
            if(hasTrack&&state!=null&&(state.getState()==PlaybackState.STATE_PAUSED||state.getState()==PlaybackState.STATE_STOPPED)&&(state.getActions()&(PlaybackState.ACTION_PLAY|PlaybackState.ACTION_PLAY_PAUSE))!=0){
                dispatched=true;removeListener();PlayerControl.operate(context,c,"play",request,(display,spoken)->complete(display,spoken));return;
            }
            if(selection.id==null){finish("Плеер не предоставил однозначный музыкальный микс. Выберите музыку в приложении.");return;}
            if(!active.getAsBoolean()){finish(null);return;}
            catalogController=c;catalogObserver=new MediaController.Callback(){@Override public void onPlaybackStateChanged(PlaybackState ignored){verifyCatalog();}@Override public void onSessionDestroyed(){finish("Медиасессия завершилась; воспроизведение не подтверждено.");}};
            try{c.registerCallback(catalogObserver,main);PlaybackState latest=c.getPlaybackState();if(latest!=null&&latest.getState()==PlaybackState.STATE_PLAYING){complete(PlayerControl.describe(context,c),"Музыка уже играет.");return;}dispatched=true;removeListener();c.getTransportControls().playFromMediaId(selection.id,null);verifyCatalog();}
            catch(RuntimeException e){finish("Плеер не принял запрос на запуск микса.");}
        }
        void verifyCatalog(){
            if(done||catalogController==null)return;main.removeCallbacks(verify);
            try{PlaybackState state=catalogController.getPlaybackState();if(state!=null&&state.getState()==PlaybackState.STATE_PLAYING){complete(PlayerControl.describe(context,catalogController),"Включаю музыку.");return;}if(state!=null&&state.getState()==PlaybackState.STATE_ERROR){finish("Плеер сообщил ошибку воспроизведения.");return;}main.postDelayed(verify,200);}
            catch(RuntimeException e){finish("Связь с плеером потеряна; воспроизведение не подтверждено.");}
        }
        void finish(String text){complete(text,text);}
        void removeListener(){try{manager.removeOnActiveSessionsChangedListener(listener);}catch(RuntimeException ignored){}}
        void complete(String display,String spoken){
            if(done)return;done=true;main.removeCallbacks(poll);main.removeCallbacks(verify);main.removeCallbacks(watchdog);if(cancelBrowser!=null)cancelBrowser.run();if(cancelCatalog!=null)cancelCatalog.run();if(catalogController!=null&&catalogObserver!=null)try{catalogController.unregisterCallback(catalogObserver);}catch(RuntimeException ignored){}removeListener();if(pending==this)pending=null;
            if(display!=null&&active.getAsBoolean())reply.result(display,spoken);
        }
        static boolean nonempty(String s){return s!=null&&!s.trim().isEmpty();}
    }
    private MusicLaunchCoordinator(){}
}
