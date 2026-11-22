package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.*;
import android.content.pm.ResolveInfo;
import android.media.browse.MediaBrowser;
import android.os.Bundle;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Read-only public browse capability probe; emits counts, never media IDs or titles. */
final class MusicBrowserProbe {
    static void run(Instrumentation runner,Context context)throws Exception{
        run(runner,context,false);
    }
    static void run(Instrumentation runner,Context context,boolean tryPlayback)throws Exception{
        String pkg=PlayerTargets.packageName(context,"music");
        List<ResolveInfo> services=context.getPackageManager().queryIntentServices(new Intent("android.media.browse.MediaBrowserService").setPackage(pkg),0);
        services.removeIf(x->x.serviceInfo==null||!x.serviceInfo.exported||!x.serviceInfo.enabled);
        Bundle report=new Bundle();report.putInt("browser_services",services.size());
        if(services.size()!=1){runner.sendStatus(0,report);return;}
        CountDownLatch done=new CountDownLatch(1);MediaBrowser[] browser=new MediaBrowser[1];AtomicReference<String> status=new AtomicReference<>("timeout"),preferredKind=new AtomicReference<>("none"),preferredId=new AtomicReference<>("");AtomicInteger browsable=new AtomicInteger(),playable=new AtomicInteger(),musicCategory=new AtomicInteger(),preferred=new AtomicInteger(),preferredBrowsable=new AtomicInteger(),preferredPlayable=new AtomicInteger(),preferredChildPlayable=new AtomicInteger(),emptyTitle=new AtomicInteger(),pending=new AtomicInteger(1),childErrors=new AtomicInteger();AtomicBoolean playFromId=new AtomicBoolean(),playerMatches=new AtomicBoolean();
        runner.runOnMainSync(()->{
            ComponentName component=new ComponentName(pkg,services.get(0).serviceInfo.name);
            browser[0]=new MediaBrowser(context,component,new MediaBrowser.ConnectionCallback(){
                @Override public void onConnected(){
                    status.set("connected");
                    try{android.media.session.MediaController c=new android.media.session.MediaController(context,browser[0].getSessionToken());playerMatches.set(pkg.equals(c.getPackageName()));android.media.session.PlaybackState s=c.getPlaybackState();playFromId.set(s!=null&&(s.getActions()&android.media.session.PlaybackState.ACTION_PLAY_FROM_MEDIA_ID)!=0);}catch(RuntimeException ignored){}
                    try{String root=browser[0].getRoot();browser[0].subscribe(root,new MediaBrowser.SubscriptionCallback(){
                        @Override public void onChildrenLoaded(String id,List<MediaBrowser.MediaItem> items){
                            int inspected=0;
                            for(MediaBrowser.MediaItem item:items){if(++inspected>50)break;if(item.isBrowsable())browsable.incrementAndGet();if(item.isPlayable())playable.incrementAndGet();CharSequence title=item.getDescription().getTitle();String t=title==null?"":title.toString().toLowerCase(Locale.ROOT);if(t.isEmpty())emptyTitle.incrementAndGet();if(t.matches(".*(микс|подборк|playlist|плейлист|музык|music|любим|избран|favorite|recommend|рекоменд).*"))musicCategory.incrementAndGet();boolean match=t.matches("^(моя волна|мой микс|любимые треки|избранные треки|my mix|liked songs|favorites)$");if(match){preferred.incrementAndGet();preferredKind.set(t);if(item.getMediaId()!=null)preferredId.set(item.getMediaId());if(item.isBrowsable())preferredBrowsable.incrementAndGet();if(item.isPlayable())preferredPlayable.incrementAndGet();}if(id.equals(preferredId.get())&&item.isPlayable())preferredChildPlayable.incrementAndGet();
                                boolean descend=id.equals(root)&&item.isBrowsable()&&inspected<=3;
                                if(match&&item.isBrowsable()&&!id.equals(preferredId.get())){preferredId.set(item.getMediaId());descend=true;}
                                if(descend&&item.getMediaId()!=null){pending.incrementAndGet();try{browser[0].subscribe(item.getMediaId(),this);}catch(RuntimeException e){childErrors.incrementAndGet();pending.decrementAndGet();}}
                            }
                            status.set("children_loaded");if(pending.decrementAndGet()==0)done.countDown();
                        }
                        @Override public void onError(String id){childErrors.incrementAndGet();if(id.equals(root))status.set("browse_denied");if(pending.decrementAndGet()==0)done.countDown();}
                    });}catch(RuntimeException e){status.set("browse_error");done.countDown();}
                }
                @Override public void onConnectionFailed(){status.set("connection_denied");done.countDown();}
                @Override public void onConnectionSuspended(){status.set("connection_suspended");done.countDown();}
            },null);try{browser[0].connect();}catch(RuntimeException e){status.set("connect_error");done.countDown();}
        });
        try{
            done.await(7,TimeUnit.SECONDS);
            if(tryPlayback&&preferred.get()==1&&preferredPlayable.get()==1&&!preferredId.get().isEmpty()&&playerMatches.get()){
                android.media.session.MediaController c=new android.media.session.MediaController(context,browser[0].getSessionToken());android.media.session.PlaybackState before=c.getPlaybackState();
                if(before!=null&&before.getState()==android.media.session.PlaybackState.STATE_PLAYING)report.putString("preferred_play_probe","already_playing_no_dispatch");
                else{
                    runner.runOnMainSync(()->c.getTransportControls().playFromMediaId(preferredId.get(),null));
                    boolean playing=false;for(int i=0;i<35;i++){Thread.sleep(200);android.media.session.PlaybackState s=c.getPlaybackState();if(s!=null&&s.getState()==android.media.session.PlaybackState.STATE_PLAYING){playing=true;break;}}
                    report.putString("preferred_play_probe",playing?"playing_confirmed":"unconfirmed");
                    if(playing){runner.runOnMainSync(()->c.getTransportControls().pause());boolean paused=false;for(int i=0;i<15;i++){Thread.sleep(200);android.media.session.PlaybackState s=c.getPlaybackState();if(s!=null&&s.getState()==android.media.session.PlaybackState.STATE_PAUSED){paused=true;break;}}report.putString("preferred_restore",paused?"paused":"unconfirmed");}
                }
            }else if(tryPlayback)report.putString("preferred_play_probe","no_unique_playable_preference");
        }finally{runner.runOnMainSync(()->{if(browser[0]!=null)browser[0].disconnect();});}
        report.putString("browser_status",status.get());report.putInt("browsable_count",browsable.get());report.putInt("playable_count",playable.get());report.putInt("music_category_count",musicCategory.get());report.putInt("preferred_label_count",preferred.get());report.putString("preferred_kind",preferredKind.get());report.putBoolean("preferred_has_id",!preferredId.get().isEmpty());report.putBoolean("player_matches",playerMatches.get());report.putBoolean("play_from_id_advertised",playFromId.get());report.putInt("preferred_browsable",preferredBrowsable.get());report.putInt("preferred_playable",preferredPlayable.get());report.putInt("preferred_child_playable",preferredChildPlayable.get());report.putInt("empty_title_count",emptyTitle.get());report.putInt("child_errors",childErrors.get());report.putInt("pending_callbacks",pending.get());runner.sendStatus(0,report);
    }
    private MusicBrowserProbe(){}
}
