package ru.wildlik.wileyai.mobile;

import android.content.Context;

/** Preserve the legacy default on upgrades that never saved an explicit phrase. */
final class WakeSettings {
    static void initializeNewInstall(Context context){
        var settings=context.getSharedPreferences("wiley-mobile",Context.MODE_PRIVATE);
        if(!settings.contains("wake_phrase")&&defaultPhrase(context).equals(WakePhrase.SHORT)){
            settings.edit().putString("wake_phrase",WakePhrase.SHORT).apply();
        }
    }
    static String defaultPhrase(Context context){
        try{
            var info=context.getPackageManager().getPackageInfo(context.getPackageName(),0);
            return info.firstInstallTime==info.lastUpdateTime?WakePhrase.SHORT:WakePhrase.DEFAULT;
        }catch(Exception unavailable){return WakePhrase.DEFAULT;}
    }
    private WakeSettings(){}
}
