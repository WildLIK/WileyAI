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
    static void transport(Instrumentation runner,Context context)throws Exception{
        Player[] player=new Player[1];runner.runOnMainSync(()->player[0]=new Player(context));
        try{
            String playing=command(runner,context,player[0],"play");check(playing.contains("воспроизводится"));check(player[0].state==PlaybackState.STATE_PLAYING);
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
            check(command(runner,context,player[0],"play").contains("не подтвердил"));check(player[0].calls==1); // No automatic retry/toggle.
        }finally{runner.runOnMainSync(player[0]::close);}
    }
    static void cold(Instrumentation runner,Context context)throws Exception{
        Player[] player=new Player[1];runner.runOnMainSync(()->{player[0]=new Player(context);player[0].state=PlaybackState.STATE_NONE;player[0].actions=0;player[0].publish();});
        try{CountDownLatch done=new CountDownLatch(1);AtomicReference<String> response=new AtomicReference<>();runner.runOnMainSync(()->PlayerControl.resume(context,player[0].controller,text->{response.set(text);done.countDown();}));check(done.await(6,TimeUnit.SECONDS));check(player[0].calls==1);check(player[0].state==PlaybackState.STATE_PLAYING);check(response.get().contains("воспроизводится"));}finally{runner.runOnMainSync(player[0]::close);}
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
