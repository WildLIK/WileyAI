package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.*;
import android.media.MediaMetadata;
import android.media.session.*;
import android.os.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Uses a real app-owned Android MediaSession, with no sound or external player mutation. */
final class MediaProbe {
    private static final long ACTIONS=PlaybackState.ACTION_PLAY|PlaybackState.ACTION_PAUSE|PlaybackState.ACTION_SKIP_TO_NEXT|PlaybackState.ACTION_SKIP_TO_PREVIOUS|PlaybackState.ACTION_SEEK_TO;
    private static void check(boolean value){if(!value)throw new AssertionError("Media probe failed");}
    private static final class Player implements AutoCloseable {
        final MediaSession session; final MediaController controller; int state=PlaybackState.STATE_PAUSED,track=1,calls;long position=10000,actions=ACTIONS;boolean ignore,restartPrevious;
        Player(Context context){
            session=new MediaSession(context,"WileyAI-media-device-probe");controller=new MediaController(context,session.getSessionToken());
            session.setCallback(new MediaSession.Callback(){
                public void onPlay(){calls++;if(!ignore){state=PlaybackState.STATE_PLAYING;publish();}}
                public void onPlayFromMediaId(String id,Bundle extras){calls++;if(!ignore){state=PlaybackState.STATE_PLAYING;publish();}}
                public void onPause(){calls++;state=PlaybackState.STATE_PAUSED;publish();}
                public void onSkipToNext(){calls++;track++;position=0;publish();}
                public void onSkipToPrevious(){calls++;if(!restartPrevious)track--;position=0;publish();}
                public void onSeekTo(long target){calls++;position=target;publish();}
            },new Handler(Looper.getMainLooper()));session.setActive(true);publish();
        }
        void publish(){session.setMetadata(new MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_MEDIA_ID,"probe-"+track).putString(MediaMetadata.METADATA_KEY_TITLE,"Public test "+track).putLong(MediaMetadata.METADATA_KEY_DURATION,600000).build());session.setPlaybackState(new PlaybackState.Builder().setState(state,position,state==PlaybackState.STATE_PLAYING?1:0,SystemClock.elapsedRealtime()).setActions(actions).build());}
        public void close(){session.setActive(false);session.release();}
    }
    private static String command(Instrumentation runner,Context context,Player player,String action)throws Exception{
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String> response=new AtomicReference<>();runner.runOnMainSync(()->PlayerControl.operate(context,player.controller,action,text->{response.set(text);done.countDown();}));check(done.await(6,TimeUnit.SECONDS));check(response.get()!=null);return response.get();
    }
    private static String[] commandSpeech(Instrumentation runner,Context context,Player player,String action,String request)throws Exception{
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String[]> response=new AtomicReference<>();runner.runOnMainSync(()->PlayerControl.operate(context,player.controller,action,request,(display,spoken)->{response.set(new String[]{display,spoken});done.countDown();}));check(done.await(6,TimeUnit.SECONDS));return response.get();
    }
    static void transport(Instrumentation runner,Context context)throws Exception{
        Player[] player=new Player[1];runner.runOnMainSync(()->player[0]=new Player(context));
        try{
            String playing=command(runner,context,player[0],"play");check(playing.contains("воспроизводится"));check(player[0].state==PlaybackState.STATE_PLAYING);
            String[] stopped=commandSpeech(runner,context,player[0],"pause","Останови музыку");check(stopped[0].contains("Public test 1"));check(stopped[0].contains("10:00"));check(stopped[1].equals("Музыка остановлена."));
            String[] status=commandSpeech(runner,context,player[0],"status","Что сейчас играет?");check(status[1].equals("Public test 1."));check(!status[1].contains("10:00"));
            command(runner,context,player[0],"play");
            check(command(runner,context,player[0],"pause").contains("на паузе"));int count=player[0].calls;command(runner,context,player[0],"pause");check(player[0].calls==count);
            runner.runOnMainSync(()->{player[0].actions=PlaybackState.ACTION_PLAY_PAUSE;player[0].publish();});
            check(command(runner,context,player[0],"play").contains("воспроизводится"));check(command(runner,context,player[0],"pause").contains("на паузе"));
            runner.runOnMainSync(()->{player[0].actions=ACTIONS;player[0].publish();});
            check(command(runner,context,player[0],"seek:30000").startsWith("Позиция изменена"));check(player[0].position==40000);
            check(command(runner,context,player[0],"position:150000").startsWith("Позиция изменена"));check(player[0].position==150000);
            check(command(runner,context,player[0],"next").contains("Public test 2"));check(player[0].track==2);
            check(command(runner,context,player[0],"previous").contains("Public test 1"));check(player[0].track==1);
            runner.runOnMainSync(()->{player[0].restartPrevious=true;player[0].position=10000;player[0].publish();});int previousCalls=player[0].calls;
            check(command(runner,context,player[0],"previous").contains("начало текущего трека"));check(player[0].track==1&&player[0].calls==previousCalls+1);
        }finally{runner.runOnMainSync(player[0]::close);}
    }
    static void failure(Instrumentation runner,Context context)throws Exception{
        Player[] player=new Player[1];runner.runOnMainSync(()->{player[0]=new Player(context);player[0].actions=PlaybackState.ACTION_PLAY;player[0].ignore=true;player[0].publish();});
        try{
            check(command(runner,context,player[0],"next").contains("не предоставляет"));check(player[0].calls==0);
            String[] failed=commandSpeech(runner,context,player[0],"play","Включи музыку");check(failed[0].contains("не подтвердил"));check(failed[1].contains("не подтвердил"));check(player[0].calls==1); // No automatic retry/toggle.
        }finally{runner.runOnMainSync(player[0]::close);}
    }
    static void cold(Instrumentation runner,Context context)throws Exception{
        Player[] player=new Player[1];runner.runOnMainSync(()->{player[0]=new Player(context);player[0].state=PlaybackState.STATE_NONE;player[0].actions=0;player[0].publish();});
        try{CountDownLatch done=new CountDownLatch(1);AtomicReference<String> response=new AtomicReference<>();runner.runOnMainSync(()->PlayerControl.resume(context,player[0].controller,text->{response.set(text);done.countDown();}));check(done.await(6,TimeUnit.SECONDS));check(player[0].calls==1);check(player[0].state==PlaybackState.STATE_PLAYING);check(response.get().contains("воспроизводится"));}finally{runner.runOnMainSync(player[0]::close);}
    }
    static void coldCoordinator(Instrumentation runner,Context context)throws Exception{
        android.content.SharedPreferences prefs=context.getSharedPreferences("music-cold-probe",0);
        prefs.edit().putString("preferred_music",context.getPackageName()+"/.MainActivity").commit();
        Context isolated=new ContextWrapper(context){@Override public android.content.SharedPreferences getSharedPreferences(String name,int mode){return prefs;}};
        Player[] player=new Player[1];CountDownLatch done=new CountDownLatch(2);AtomicReference<String> first=new AtomicReference<>(),second=new AtomicReference<>();
        runner.runOnMainSync(()->{player[0]=new Player(context);player[0].state=PlaybackState.STATE_NONE;player[0].publish();
            PhoneCommands.Action action=new PhoneCommands.Action("media","play","music");
            java.util.function.Consumer<Intent> launch=intent->new Handler(Looper.getMainLooper()).postDelayed(()->{player[0].state=PlaybackState.STATE_PAUSED;player[0].publish();},300);
            PlayerControl.execute(isolated,action,"Включи музыку",launch,()->true,(display,spoken)->{first.set(spoken);done.countDown();});
            PlayerControl.execute(isolated,action,"Включи музыку",launch,()->true,(display,spoken)->{second.set(spoken);done.countDown();});
        });
        try{check(done.await(12,TimeUnit.SECONDS));check("Включаю музыку.".equals(first.get()));check(second.get().contains("Дождитесь"));check(player[0].calls==1);check(player[0].state==PlaybackState.STATE_PLAYING);}
        finally{runner.runOnMainSync(player[0]::close);prefs.edit().clear().commit();}
    }
    static void coldCoordinatorCancel(Instrumentation runner,Context context)throws Exception{
        android.content.SharedPreferences prefs=context.getSharedPreferences("music-cold-cancel-probe",0);
        prefs.edit().putString("preferred_music",context.getPackageName()+"/.MainActivity").commit();
        Context isolated=new ContextWrapper(context){@Override public android.content.SharedPreferences getSharedPreferences(String name,int mode){return prefs;}};
        Player[] player=new Player[1];java.util.concurrent.atomic.AtomicBoolean active=new java.util.concurrent.atomic.AtomicBoolean(true),replied=new java.util.concurrent.atomic.AtomicBoolean();
        runner.runOnMainSync(()->{player[0]=new Player(context);player[0].state=PlaybackState.STATE_NONE;player[0].publish();
            PhoneCommands.Action action=new PhoneCommands.Action("media","play","music");
            PlayerControl.execute(isolated,action,"Включи музыку",intent->{active.set(false);new Handler(Looper.getMainLooper()).postDelayed(()->{player[0].state=PlaybackState.STATE_PAUSED;player[0].publish();},400);},active::get,(display,spoken)->replied.set(true));
        });
        try{Thread.sleep(1000);check(player[0].calls==0);check(!replied.get());check(!MusicLaunchCoordinator.busy());}
        finally{runner.runOnMainSync(player[0]::close);prefs.edit().clear().commit();}
    }
    static void coldCoordinatorTimeout(Instrumentation runner,Context context)throws Exception{
        android.content.SharedPreferences prefs=context.getSharedPreferences("music-cold-timeout-probe",0);
        prefs.edit().putString("preferred_music",context.getPackageName()+"/.MainActivity").commit();
        Context isolated=new ContextWrapper(context){@Override public android.content.SharedPreferences getSharedPreferences(String name,int mode){return prefs;}};
        Player[] player=new Player[1];CountDownLatch done=new CountDownLatch(1);AtomicReference<String> response=new AtomicReference<>();
        runner.runOnMainSync(()->{player[0]=new Player(context);player[0].state=PlaybackState.STATE_NONE;player[0].publish();
            PlayerControl.execute(isolated,new PhoneCommands.Action("media","play","music"),"Включи музыку",intent->{},()->true,(display,spoken)->{response.set(spoken);done.countDown();});
        });
        try{check(done.await(23,TimeUnit.SECONDS));check(response.get().contains("не предоставил"));check(player[0].calls==0);}
        finally{runner.runOnMainSync(player[0]::close);prefs.edit().clear().commit();}
    }
    static void coldCoordinatorLostCallback(Instrumentation runner,Context context)throws Exception{
        android.content.SharedPreferences prefs=context.getSharedPreferences("music-cold-watchdog-probe",0);
        prefs.edit().putString("preferred_music",context.getPackageName()+"/.MainActivity").commit();
        Context isolated=new ContextWrapper(context){@Override public android.content.SharedPreferences getSharedPreferences(String name,int mode){return prefs;}};
        Player[] player=new Player[1];CountDownLatch done=new CountDownLatch(1);AtomicReference<String> response=new AtomicReference<>();AtomicInteger count=new AtomicInteger();AtomicReference<Object> job=new AtomicReference<>();
        runner.runOnMainSync(()->{try{player[0]=new Player(context);player[0].state=PlaybackState.STATE_NONE;player[0].publish();
            PlayerControl.execute(isolated,new PhoneCommands.Action("media","play","music"),"Включи музыку",intent->{},()->true,(display,spoken)->{response.set(spoken);count.incrementAndGet();done.countDown();});
            java.lang.reflect.Field pending=MusicLaunchCoordinator.class.getDeclaredField("pending");pending.setAccessible(true);Object current=pending.get(null);job.set(current);java.lang.reflect.Field dispatched=current.getClass().getDeclaredField("dispatched");dispatched.setAccessible(true);dispatched.setBoolean(current,true);
        }catch(Exception e){throw new RuntimeException(e);}});
        try{
            check(done.await(23,TimeUnit.SECONDS));check(response.get().contains("не подтвердил запуск вовремя"));check(!MusicLaunchCoordinator.busy());
            runner.runOnMainSync(()->{try{java.lang.reflect.Method late=job.get().getClass().getDeclaredMethod("complete",String.class,String.class);late.setAccessible(true);late.invoke(job.get(),"late","late");}catch(Exception e){throw new RuntimeException(e);}});
            check(count.get()==1);check(player[0].calls==0);
        }finally{runner.runOnMainSync(player[0]::close);prefs.edit().clear().commit();}
    }
    static void coldCatalog(Instrumentation runner,Context context)throws Exception{
        android.content.SharedPreferences prefs=context.getSharedPreferences("music-cold-catalog-probe",0);
        prefs.edit().putString("preferred_music",context.getPackageName()+"/.MainActivity").commit();
        Context isolated=new ContextWrapper(context){@Override public android.content.SharedPreferences getSharedPreferences(String name,int mode){return prefs;}};
        Player[] player=new Player[1];CountDownLatch done=new CountDownLatch(1);AtomicReference<String> response=new AtomicReference<>();
        runner.runOnMainSync(()->{try{player[0]=new Player(context);player[0].state=PlaybackState.STATE_NONE;player[0].publish();
            PlayerControl.execute(isolated,new PhoneCommands.Action("media","play","music"),"Включи музыку",intent->{},()->true,(display,spoken)->{response.set(spoken);done.countDown();});
            java.lang.reflect.Field pending=MusicLaunchCoordinator.class.getDeclaredField("pending");pending.setAccessible(true);Object job=pending.get(null);java.lang.reflect.Field started=job.getClass().getDeclaredField("catalogStarted");started.setAccessible(true);started.setBoolean(job,true);java.lang.reflect.Field chosen=job.getClass().getDeclaredField("selection");chosen.setAccessible(true);chosen.set(job,new MusicCatalogSelector.Selection(player[0].controller,"test-mix-id"));java.lang.reflect.Method check=job.getClass().getDeclaredMethod("check");check.setAccessible(true);check.invoke(job);
        }catch(Exception e){throw new RuntimeException(e);}});
        try{check(done.await(5,TimeUnit.SECONDS));check("Включаю музыку.".equals(response.get()));check(player[0].calls==1);check(player[0].state==PlaybackState.STATE_PLAYING);check(!MusicLaunchCoordinator.busy());}
        finally{runner.runOnMainSync(player[0]::close);prefs.edit().clear().commit();}
    }
    static void intents(Instrumentation runner,Context context)throws Exception{
        android.content.SharedPreferences preferences=context.getSharedPreferences("media-intent-probe",0);preferences.edit().putString("preferred_music","ru.mts.music.android/.ui.MainScreenActivity").putString("preferred_video","com.google.android.youtube/unused").commit();
        Context isolated=new ContextWrapper(context){@Override public android.content.SharedPreferences getSharedPreferences(String name,int mode){return preferences;}};
        try{
            for(PhoneCommands.Action action:new PhoneCommands.Action[]{PhoneCommands.parse("найди видео Big Buck Bunny",true),PhoneCommands.parse("включи песню Вальс цветов",true),PhoneCommands.parse("найди песню Вальс цветов",true)}){
                AtomicReference<Intent> intent=new AtomicReference<>();AtomicReference<String> response=new AtomicReference<>();runner.runOnMainSync(()->MediaNavigation.execute(isolated,action,intent::set,response::set));check(intent.get()!=null);check(intent.get().getComponent()!=null);check(intent.get().getComponent().getPackageName().equals(action.target.equals("youtube")?"com.google.android.youtube":"ru.mts.music.android"));check(!response.get().isEmpty());
            }
        }finally{preferences.edit().clear().commit();}
    }
    static void permissionMetadata(Context context)throws Exception{
        android.content.pm.ServiceInfo info=context.getPackageManager().getServiceInfo(new ComponentName(context,MediaAccessService.class),android.content.pm.PackageManager.GET_META_DATA);
        check(!info.exported);check("android.permission.BIND_NOTIFICATION_LISTENER_SERVICE".equals(info.permission));check(info.metaData.containsKey("android.service.notification.default_filter_types"));check("".equals(info.metaData.getString("android.service.notification.default_filter_types")));
        String disabled=info.metaData.getString("android.service.notification.disabled_filter_types");for(String type:new String[]{"conversations","alerting","silent","ongoing"})check(java.util.Arrays.asList(disabled.split(",")).contains(type));
    }
    private MediaProbe(){}
}
