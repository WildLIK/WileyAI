package ru.wildlik.wileyai.mobile;
import android.content.SharedPreferences;
import org.json.JSONObject;
import java.util.*;
/** Local, bounded mappings. Conflicting choices never silently replace a mapping. */
final class AppNameMemory {
 private static final String KEY="confirmed_app_names_v1";private final SharedPreferences prefs;
 AppNameMemory(SharedPreferences p){prefs=p;}
 private JSONObject read(){try{return new JSONObject(prefs.getString(KEY,"{}"));}catch(Exception e){return new JSONObject();}}
 synchronized boolean record(String phrase,AppRegistry.App app,String source){
  String name=AppRegistry.key(phrase);if(name.isEmpty()||name.length()>60||!name.matches("[\\p{L}\\p{N} ._+-]+"))return false;
  try{JSONObject all=read();JSONObject old=all.optJSONObject(name);if(old!=null&&!app.id().equals(old.optString("id")))return false;if(old==null&&all.length()>=100)return false;
   all.put(name,new JSONObject().put("id",app.id()).put("package",app.packageName()).put("label",app.label()).put("source",source).put("time",System.currentTimeMillis()));return prefs.edit().putString(KEY,all.toString()).commit();
  }catch(Exception e){return false;}
 }
 synchronized List<AppRegistry.App> resolve(String phrase,List<AppRegistry.App> entries){JSONObject row=read().optJSONObject(AppRegistry.key(phrase));if(row==null)return List.of();for(AppRegistry.App app:entries)if(app.id().equals(row.optString("id"))&&app.packageName().equals(row.optString("package")))return List.of(app);return List.of();}
 synchronized Map<String,String> entries(){JSONObject all=read();Map<String,String> out=new TreeMap<>();Iterator<String> keys=all.keys();while(keys.hasNext()){String k=keys.next();JSONObject item=all.optJSONObject(k);if(item!=null)out.put(k,item.optString("label")+" · "+item.optString("package"));}return out;}
 synchronized void remove(String phrase){JSONObject all=read();all.remove(phrase);prefs.edit().putString(KEY,all.toString()).apply();}
 synchronized boolean rename(String oldName,String newName){try{String name=AppRegistry.key(newName);if(name.isEmpty()||name.length()>60||!name.matches("[\\p{L}\\p{N} ._+-]+"))return false;JSONObject all=read();JSONObject row=all.optJSONObject(oldName);if(row==null||(!name.equals(oldName)&&all.has(name)))return false;all.remove(oldName);all.put(name,row);return prefs.edit().putString(KEY,all.toString()).commit();}catch(Exception e){return false;}}
 synchronized void clear(){prefs.edit().remove(KEY).apply();}
}
