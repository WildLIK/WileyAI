package ru.wildlik.wileyai.mobile;

import android.content.*;
import android.content.pm.ResolveInfo;
import android.media.browse.MediaBrowser;
import android.media.session.MediaController;
import android.os.*;
import java.util.*;
import java.util.function.Consumer;

/** Bounded read-only search of the chosen player's public media catalogue. */
final class MusicCatalogSelector {
    static final class Selection { final MediaController controller;final String id; Selection(MediaController controller,String id){this.controller=controller;this.id=id;} }
    static Runnable find(Context context,String pkg,Consumer<Selection> result){
        List<ResolveInfo> services=context.getPackageManager().queryIntentServices(new Intent("android.media.browse.MediaBrowserService").setPackage(pkg),0);
        services.removeIf(x->x.serviceInfo==null||!x.serviceInfo.exported||!x.serviceInfo.enabled);
        if(services.size()!=1){result.accept(null);return ()->{};}
        Search search=new Search(context,pkg,services.get(0),result);search.start();return search::cancel;
    }
    private static final class Search {
        final Context context;final String pkg;final ResolveInfo service;final Consumer<Selection> result;final Handler main=new Handler(Looper.getMainLooper());
        final Map<String,Integer> matches=new LinkedHashMap<>();final Set<String> subscribed=new HashSet<>();
        MediaBrowser browser;MediaController controller;boolean done;int outstanding,visited;final Runnable timeout=()->finish(null);
        Search(Context context,String pkg,ResolveInfo service,Consumer<Selection> result){this.context=context;this.pkg=pkg;this.service=service;this.result=result;}
        void start(){
            try{
                browser=new MediaBrowser(context,new ComponentName(pkg,service.serviceInfo.name),new MediaBrowser.ConnectionCallback(){
                    @Override public void onConnected(){if(done)return;try{controller=new MediaController(context,browser.getSessionToken());if(!pkg.equals(controller.getPackageName())){finish(null);return;}subscribe(browser.getRoot(),0);}catch(RuntimeException e){finish(null);}}
                    @Override public void onConnectionFailed(){finish(null);}
                    @Override public void onConnectionSuspended(){finish(null);}
                },null);
                main.postDelayed(timeout,7000);browser.connect();
            }catch(RuntimeException e){finish(null);}
        }
        void subscribe(String id,int depth){
            if(done||id==null||id.isEmpty()||!subscribed.add(id))return;
            outstanding++;
            try{browser.subscribe(id,new MediaBrowser.SubscriptionCallback(){
                @Override public void onChildrenLoaded(String parent,List<MediaBrowser.MediaItem> items){
                    if(done)return;
                    if(items!=null){int visitedHere=0;for(MediaBrowser.MediaItem item:items){
                        if(item==null||++visitedHere>50||++visited>150)break;
                        String mediaId=item.getMediaId();android.media.MediaDescription description=item.getDescription();CharSequence title=description==null?null:description.getTitle();int rank=MusicCatalogPolicy.rank(title==null?null:title.toString(),item.isPlayable(),mediaId);
                        if(rank>0)matches.merge(mediaId,rank,Math::max);
                        if(depth==0&&item.isBrowsable()&&visitedHere<=3)subscribe(mediaId,1);
                    }}
                    if(--outstanding==0)choose();
                }
                @Override public void onError(String parent){if(!done&&--outstanding==0)choose();}
            });}catch(RuntimeException e){if(--outstanding==0)choose();}
        }
        void choose(){
            int best=0,count=0;String selected=null;
            for(Map.Entry<String,Integer> item:matches.entrySet()){int rank=item.getValue();if(rank>best){best=rank;selected=item.getKey();count=1;}else if(rank==best)count++;}
            main.removeCallbacks(timeout);result.accept(new Selection(controller,count==1?selected:null));
        }
        void finish(Selection selection){if(done)return;cancel();result.accept(selection);}
        void cancel(){if(done)return;done=true;main.removeCallbacks(timeout);if(browser!=null)try{browser.disconnect();}catch(RuntimeException ignored){}}
    }
    private MusicCatalogSelector(){}
}
