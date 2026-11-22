package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import java.security.MessageDigest;
import java.util.*;

/** User-granted package/signing-identity permissions, separate from Android consent. */
final class ScreenAppPermissions {
    private static final String KEY="screen_allowed_apps";
    static String identity(Context context,String pkg){
        if(android.os.Build.VERSION.SDK_INT<28)return "";
        try{
            PackageInfo info=context.getPackageManager().getPackageInfo(pkg,PackageManager.GET_SIGNING_CERTIFICATES);
            if(info.signingInfo==null)return "";
            Signature[] signatures=info.signingInfo.getApkContentsSigners();if(signatures==null||signatures.length==0)return "";
            List<String> digests=new ArrayList<>();for(Signature sig:signatures){byte[] hash=MessageDigest.getInstance("SHA-256").digest(sig.toByteArray());StringBuilder hex=new StringBuilder();for(byte b:hash)hex.append(String.format(Locale.ROOT,"%02x",b&255));digests.add(hex.toString());}
            Collections.sort(digests);return pkg+"|"+String.join(",",digests);
        }catch(Exception e){return "";}
    }
    static boolean allowed(Context context,String pkg){
        if(pkg==null||ScreenPrivacy.protectedName(pkg))return false;
        if(ScreenPrivacy.trustedPackage(pkg,context.getPackageName()))return true;
        try{
            var info=context.getPackageManager().getApplicationInfo(pkg,0);String label=String.valueOf(context.getPackageManager().getApplicationLabel(info));
            if(ScreenPrivacy.protectedName(label))return false;
        }catch(Exception e){return false;}
        String key=identity(context,pkg);return !key.isEmpty()&&context.getSharedPreferences("wiley-mobile",0).getStringSet(KEY,Set.of()).contains(key);
    }
    static boolean stillAllowed(Context context,String pkg,String identity){
        if(pkg==null||ScreenPrivacy.protectedName(pkg))return false;
        if(ScreenPrivacy.trustedPackage(pkg,context.getPackageName()))return true;
        return !identity.isEmpty()&&context.getSharedPreferences("wiley-mobile",0).getStringSet(KEY,Set.of()).contains(identity);
    }
    static boolean grant(Context context,String pkg){
        if(pkg==null||ScreenPrivacy.protectedName(pkg))return false;
        try{var app=context.getPackageManager().getApplicationInfo(pkg,0);if(ScreenPrivacy.protectedName(String.valueOf(context.getPackageManager().getApplicationLabel(app))))return false;}catch(Exception e){return false;}
        String id=identity(context,pkg);if(id.isEmpty())return false;
        var prefs=context.getSharedPreferences("wiley-mobile",0);Set<String> keys=new HashSet<>(prefs.getStringSet(KEY,Set.of()));keys.removeIf(x->x.startsWith(pkg+"|"));keys.add(id);return prefs.edit().putStringSet(KEY,keys).commit();
    }
    static void revoke(Context context,String pkg){var prefs=context.getSharedPreferences("wiley-mobile",0);Set<String> keys=new HashSet<>(prefs.getStringSet(KEY,Set.of()));keys.removeIf(x->x.startsWith(pkg+"|"));prefs.edit().putStringSet(KEY,keys).apply();}
    private ScreenAppPermissions(){}
}
