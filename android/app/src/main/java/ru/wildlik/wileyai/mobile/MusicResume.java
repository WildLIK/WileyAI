package ru.wildlik.wileyai.mobile;

import android.content.*;
import android.content.pm.ResolveInfo;
import android.media.browse.MediaBrowser;
import android.media.session.MediaController;
import android.os.*;
import java.util.*;
import java.util.function.Consumer;

/** Reconnects a chosen music app through its public MediaBrowserService to resume its queue. */
final class MusicResume {
    static void connect(Context context,String pkg,Consumer<String> reply){
        List<ResolveInfo> services=context.getPackageManager().queryIntentServices(new Intent("android.media.browse.MediaBrowserService").setPackage(pkg),0);
        services.removeIf(item->item.serviceInfo==null||!item.serviceInfo.exported||!item.serviceInfo.enabled);
        if(services.size()!=1){reply.accept("Откройте выбранную музыку и запустите трек: приложение не предоставляет однозначную службу возобновления.");return;}
        Handler main=new Handler(Looper.getMainLooper());MediaBrowser[] browser=new MediaBrowser[1];boolean[] finished={false};
        Consumer<String> finish=text->{if(finished[0])return;finished[0]=true;if(browser[0]!=null)browser[0].disconnect();reply.accept(text);};
        ComponentName service=new ComponentName(pkg,services.get(0).serviceInfo.name);
        browser[0]=new MediaBrowser(context.getApplicationContext(),service,new MediaBrowser.ConnectionCallback(){
            @Override public void onConnected(){if(finished[0])return;try{MediaController controller=new MediaController(context,browser[0].getSessionToken());PlayerControl.resume(context,controller,finish);}catch(RuntimeException unavailable){finish.accept("Плеер не разрешил возобновление. Откройте музыку и выберите трек.");}}
            @Override public void onConnectionFailed(){finish.accept("Плеер не разрешил подключение WileyAI. Откройте музыку и запустите трек один раз.");}
            @Override public void onConnectionSuspended(){finish.accept("Связь с музыкальным приложением прервалась. Повторите после его открытия.");}
        },null);
        try{browser[0].connect();}catch(RuntimeException denied){finish.accept("Не удалось подключиться к музыкальному приложению. Откройте его и выберите трек.");}
        main.postDelayed(()->finish.accept("Музыкальное приложение не ответило. Откройте его и запустите трек один раз."),8000);
    }
    private MusicResume(){}
}
