package android.content;
public interface SharedPreferences {
    default boolean getBoolean(String key,boolean fallback){return fallback;} String getString(String key,String fallback); float getFloat(String key,float fallback); Editor edit();
    interface Editor { Editor putString(String key,String value); Editor remove(String key); void apply(); }
}
