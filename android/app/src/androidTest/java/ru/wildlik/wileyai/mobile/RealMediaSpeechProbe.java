package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.Context;
import android.media.MediaMetadata;
import android.media.session.MediaController;
import android.media.session.PlaybackState;
import android.os.Bundle;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Explicit real-player probe; no search, playlists, likes, or settings are changed. */
final class RealMediaSpeechProbe {
    private static String[] command(Instrumentation runner, Context context, String phrase) throws Exception {
        CountDownLatch done=new CountDownLatch(1); AtomicReference<String[]> result=new AtomicReference<>();
        PhoneCommands.Action action=PhoneCommands.parse(phrase,true);
        if(action==null) throw new AssertionError("Command not parsed: "+phrase);
        runner.runOnMainSync(()->PhoneActionCore.execute(context,action,phrase,(display,spoken)->{result.set(new String[]{display,spoken});done.countDown();}));
        if(!done.await(12,TimeUnit.SECONDS)) throw new AssertionError("Player timed out: "+phrase);
        return result.get();
    }
    private static void emit(Instrumentation runner,String name,String[] result){
        Bundle b=new Bundle(); b.putString("probe",name);b.putString("spoken",result[1]);b.putBoolean("display_has_metadata",result[0].contains(" · "));runner.sendStatus(0,b);
    }
    static void run(Instrumentation runner,Context context) throws Exception {
        if(!PlayerControl.permitted(context)) { Bundle b=new Bundle();b.putString("real_media","no_media_permission");runner.sendStatus(0,b);return; }
        List<MediaController> initial=PlayerControl.sessions(context);
        MediaController player=initial.size()==1?initial.get(0):null;
        PlaybackState prior=player==null?null:player.getPlaybackState();
        if(initial.size()>1) { Bundle b=new Bundle();b.putString("real_media","multiple_player_sessions");runner.sendStatus(0,b);return; }
        boolean wasPlaying=prior!=null&&prior.getState()==PlaybackState.STATE_PLAYING;
        String beforeId=player==null||player.getMetadata()==null?"":player.getMetadata().getString(MediaMetadata.METADATA_KEY_MEDIA_ID);
        String[] play=command(runner,context,"Включи музыку");emit(runner,"play",play);
        boolean playConfirmed=play[1].equals("Включаю музыку.")||play[1].equals("Музыка уже играет.");
        if(!playConfirmed) return;
        try {
            String[] already=command(runner,context,"Включи музыку");emit(runner,"already_playing",already);
            if(!already[1].equals("Музыка уже играет."))throw new AssertionError("already_playing_not_preserved");
            String[] status=command(runner,context,"Что сейчас играет");emit(runner,"status",status);
            String[] pause=command(runner,context,"Поставь на паузу");emit(runner,"pause",pause);
            String[] resume=command(runner,context,"Продолжи музыку");emit(runner,"resume",resume);
            String[] next=command(runner,context,"Следующая песня");emit(runner,"next",next);
            if(next[1].equals("Переключаю.")) { String[] previous=command(runner,context,"Предыдущая песня");emit(runner,"restore_previous",previous); }
            String[] stop=command(runner,context,"Останови музыку");emit(runner,"stop",stop);
        } finally {
            if(wasPlaying) emit(runner,"restore_playing",command(runner,context,"Продолжи музыку"));
            else emit(runner,"restore_paused",command(runner,context,"Поставь на паузу"));
            List<MediaController> after=PlayerControl.sessions(context);
            String afterId=after.size()!=1||after.get(0).getMetadata()==null?"":after.get(0).getMetadata().getString(MediaMetadata.METADATA_KEY_MEDIA_ID);
            Bundle b=new Bundle();b.putString("restoration",beforeId!=null&&!beforeId.isEmpty()&&beforeId.equals(afterId)?"track_identity_matched":"track_identity_not_confirmed");runner.sendStatus(0,b);
        }
    }
    static void screenOff(Instrumentation runner,Context context) throws Exception {
        android.os.PowerManager power=(android.os.PowerManager)context.getSystemService(Context.POWER_SERVICE);
        if(power.isInteractive())throw new AssertionError("screen_not_off");
        List<MediaController> sessions=PlayerControl.sessions(context);
        if(sessions.size()!=1||sessions.get(0).getPlaybackState()==null||sessions.get(0).getPlaybackState().getState()!=PlaybackState.STATE_PAUSED){Bundle b=new Bundle();b.putString("screen_off","no_single_paused_session");runner.sendStatus(0,b);return;}
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String[]> value=new AtomicReference<>();
        runner.runOnMainSync(()->PhoneActionCore.execute(context,PhoneCommands.parse("Включи музыку",true),"Включи музыку",null,()->true,(display,spoken)->{value.set(new String[]{display,spoken});done.countDown();}));
        if(!done.await(8,TimeUnit.SECONDS))throw new AssertionError("screen_off_timeout");
        emit(runner,"screen_off_play",value.get());
        emit(runner,"screen_off_restore_pause",command(runner,context,"Поставь на паузу"));
    }
    static void screenOffCold(Instrumentation runner,Context context) throws Exception {
        android.os.PowerManager power=(android.os.PowerManager)context.getSystemService(Context.POWER_SERVICE);
        if(power.isInteractive())throw new AssertionError("screen_not_off");
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String[]> value=new AtomicReference<>();
        runner.runOnMainSync(()->PhoneActionCore.execute(context,PhoneCommands.parse("Включи музыку",true),"Включи музыку",null,()->true,(display,spoken)->{value.set(new String[]{display,spoken});done.countDown();}));
        if(!done.await(23,TimeUnit.SECONDS))throw new AssertionError("screen_off_cold_timeout");
        emit(runner,"screen_off_cold",value.get());
        if(value.get()[1].equals("Включаю музыку.")||value.get()[1].equals("Музыка уже играет."))emit(runner,"screen_off_restore_pause",command(runner,context,"Поставь на паузу"));
    }
    private RealMediaSpeechProbe() {}
}
