package ru.wildlik.wileyai.mobile;

import android.content.*;
import java.util.*;

final class PlayerTargets {
    static String packageName(Context context,String role) {
        String id=context.getSharedPreferences("wiley-mobile",0).getString("preferred_"+(role.equals("youtube")?"video":"music"),"");
        ComponentName component=ComponentName.unflattenFromString(id); return component==null?"":component.getPackageName();
    }
    static Set<String> allowed(Context context) { Set<String> result=new HashSet<>(); for(String role:new String[]{"music","youtube"}) { String pkg=packageName(context,role); if(!pkg.isEmpty()) result.add(pkg); } return result; }
    static String label(Context context,String pkg) { try { return context.getPackageManager().getApplicationLabel(context.getPackageManager().getApplicationInfo(pkg,0)).toString(); } catch(Exception gone) { return "Плеер"; } }
    private PlayerTargets() {}
}
