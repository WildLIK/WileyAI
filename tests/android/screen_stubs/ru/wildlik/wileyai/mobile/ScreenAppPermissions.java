package ru.wildlik.wileyai.mobile;
import android.content.Context;
import java.util.*;
public class ScreenAppPermissions {
    public static final Set<String> allowedPackages=new HashSet<>();
    static boolean allowed(Context c,String pkg){return pkg!=null&&!ScreenPrivacy.protectedName(pkg)&&(ScreenPrivacy.trustedPackage(pkg,c.getPackageName())||allowedPackages.contains(pkg));}
    static String identity(Context c,String pkg){return pkg+"|test-cert";}
    static boolean stillAllowed(Context c,String pkg,String id){return allowed(c,pkg);}
}
