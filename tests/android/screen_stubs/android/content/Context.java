package android.content;
public class Context {
    public static final String ACCESSIBILITY_SERVICE="accessibility"; public boolean enabled=true;
    public String getPackageName(){return "ru.wildlik.wileyai.mobile";}
    public Prefs getSharedPreferences(String name,int mode){return new Prefs(enabled);}
    public Object getSystemService(String name){return null;}
    public android.content.pm.PackageManager getPackageManager(){return new android.content.pm.PackageManager();}
    public static class Prefs {final boolean enabled;Prefs(boolean e){enabled=e;}public boolean getBoolean(String k,boolean d){return enabled;}}
}
