package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.app.usage.*;
import android.content.*;
import android.content.pm.*;
import android.media.*;
import android.media.session.*;
import android.net.*;
import android.os.*;
import android.provider.*;
import java.time.*;
import java.util.*;
import java.util.function.*;

/** Typed, bounded Android calls. A generated URL, component, shell command or code is never accepted. */
final class AndroidToolExecutor {
    interface Host {boolean active();void launch(Intent intent);}
    private final Context context;private final AppCatalog apps;
    AndroidToolExecutor(Context context,AppCatalog apps){this.context=context;this.apps=apps;}
    private static AndroidTools.Result result(AndroidTools.Call call,String status,String summary,Map<String,Object> data){return new AndroidTools.Result(call.tool(),status,summary,data);}
    void execute(AndroidTools.Call supplied,Host host,Consumer<AndroidTools.Result> done){
        AndroidTools.Call call;try{call=AndroidTools.validate(supplied.tool(),supplied.arguments());}catch(Exception bad){done.accept(result(supplied,"invalid","Некорректный инструмент или аргументы.",Map.of()));return;}
        if(!host.active()){done.accept(result(call,"cancelled","Действие отменено.",Map.of()));return;}
        String denied=ToolPermissionManager.denied(context,call);if(!denied.isEmpty()){done.accept(result(call,"permission_required",denied,Map.of()));return;}
        try{
            String name=call.tool();Map<String,Object> args=call.arguments();
            if(name.equals("get_volume")||name.equals("adjust_volume")){AudioManager audio=(AudioManager)context.getSystemService(Context.AUDIO_SERVICE);int max=audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC),current=audio.getStreamVolume(AudioManager.STREAM_MUSIC),expected=current;if(name.equals("adjust_volume")){if(audio.isVolumeFixed())throw new IllegalStateException();int delta=Math.max(1,Math.round(max*(Integer)args.getOrDefault("percent",10)/100f));expected=Math.max(0,Math.min(max,current+(args.get("direction").equals("up")?delta:-delta)));audio.setStreamVolume(AudioManager.STREAM_MUSIC,expected,AudioManager.FLAG_SHOW_UI);}int actual=audio.getStreamVolume(AudioManager.STREAM_MUSIC);done.accept(result(call,actual==expected?"verified":"failed",PhoneActionCore.volumeDescription(actual,max),Map.of("step",actual,"max",max)));return;}
            if(name.equals("list_installed_apps")){List<Map<String,Object>> list=new ArrayList<>();for(AppRegistry.App app:apps.entries()){if(list.size()>=60)break;list.add(Map.of("name",app.label()));}done.accept(result(call,"verified","Найдено приложений: "+apps.entries().size()+". В результат включены первые "+list.size()+".",Map.of("apps",list,"total",apps.entries().size())));return;}
            if(name.equals("find_app")||name.equals("open_app")||name.equals("open_app_settings")){
                apps.resolve((String)args.get("app_name"),matches->{if(!host.active()){done.accept(result(call,"cancelled","Запуск отменён.",Map.of()));return;}if(matches.size()!=1){List<String> labels=new ArrayList<>();for(AppRegistry.App app:matches.subList(0,Math.min(5,matches.size())))labels.add(app.label());done.accept(result(call,matches.isEmpty()?"not_found":"needs_input",matches.isEmpty()?"Приложение не найдено.":"Уточните приложение: "+String.join(", ",labels),Map.of("matches",labels)));return;}
                    AppRegistry.App app=matches.get(0);if(name.equals("find_app")){done.accept(result(call,"verified","Найдено: "+app.label(),Map.of("app_name",app.label())));return;}
                    try{Intent intent;if(name.equals("open_app_settings"))intent=new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.fromParts("package",app.packageName(),null));else{ComponentName component=new ComponentName(app.packageName(),app.activity());ActivityInfo actual=context.getPackageManager().getActivityInfo(component,0);if(!actual.enabled||!actual.exported||!actual.applicationInfo.enabled)throw new IllegalStateException();intent=new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setComponent(component);}
                        host.launch(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));done.accept(result(call,"requested","Android принял запрос: "+(name.equals("open_app_settings")?"настройки ":"запуск ")+app.label()+".",Map.of("package",app.packageName(),"foreground_verified",false)));
                    }catch(Exception unavailable){done.accept(result(call,"failed","Android не разрешил открыть выбранное приложение.",Map.of()));}
                });return;
            }
            if(name.equals("set_volume")||name.equals("media_set_volume")){AudioManager audio=(AudioManager)context.getSystemService(Context.AUDIO_SERVICE);int percent=(Integer)args.get("percent"),max=audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC),expected=Math.round(max*percent/100f);if(audio.isVolumeFixed())throw new IllegalStateException();audio.setStreamVolume(AudioManager.STREAM_MUSIC,expected,AudioManager.FLAG_SHOW_UI);int actual=audio.getStreamVolume(AudioManager.STREAM_MUSIC);done.accept(result(call,actual==expected?"verified":"failed",actual==expected?PhoneActionCore.volumeDescription(actual,max):"Android не применил громкость.",Map.of("step",actual,"max",max,"percent",Math.round(actual*100f/Math.max(1,max)))));return;}
            if(name.startsWith("media_")){String target=(String)args.getOrDefault("target","active");
                if(name.equals("media_search")){MediaNavigation.execute(context,new PhoneCommands.Action("media_search",(String)args.get("query"),target),intent->{if(!host.active())throw new IllegalStateException();host.launch(intent);},text->done.accept(result(call,"requested",text,Map.of("playback_verified",false))));return;}
                String verb=name.equals("media_get_state")?"status":name.substring(6);String role=target.equals("active")?"":target;
                MediaSnapshot before=mediaSnapshot(role);PlayerControl.execute(context,new PhoneCommands.Action("media",verb,role),text->{boolean verified=mediaConfirmed(role,verb,before);done.accept(result(call,verified?"verified":"unconfirmed",text,Map.of("state_verified",verified)));});return;
            }
            if(name.equals("get_battery_status")){int percent=((BatteryManager)context.getSystemService(Context.BATTERY_SERVICE)).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);if(percent<0||percent>100)throw new IllegalStateException();done.accept(result(call,"verified","Заряд батареи: "+percent+"%.",Map.of("percent",percent)));return;}
            if(name.equals("get_device_information")){done.accept(result(call,"verified",Build.MANUFACTURER+" "+Build.MODEL+", Android "+Build.VERSION.RELEASE,Map.of("manufacturer",Build.MANUFACTURER,"model",Build.MODEL,"android",Build.VERSION.RELEASE)));return;}
            if(name.equals("get_network_status")){ConnectivityManager manager=(ConnectivityManager)context.getSystemService(Context.CONNECTIVITY_SERVICE);NetworkCapabilities caps=manager.getNetworkCapabilities(manager.getActiveNetwork());boolean available=caps!=null&&caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);done.accept(result(call,"verified",available?"Интернет доступен.":"Подключение к интернету не подтверждено.",Map.of("internet_validated",available,"metered",manager.isActiveNetworkMetered())));return;}
            if(name.equals("get_time")||name.equals("get_date")){String value=name.equals("get_time")?ZonedDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm")):LocalDate.now().toString();done.accept(result(call,"verified",name.equals("get_time")?"Сейчас "+value+" по времени телефона.":"Сегодня "+value+".",Map.of("value",value,"timezone",ZoneId.systemDefault().getId())));return;}
            if(name.equals("get_foreground_app")){UsageEvents events=((UsageStatsManager)context.getSystemService(Context.USAGE_STATS_SERVICE)).queryEvents(System.currentTimeMillis()-600000,System.currentTimeMillis());UsageEvents.Event event=new UsageEvents.Event();String pkg="";while(events.hasNextEvent()){events.getNextEvent(event);if(event.getEventType()==UsageEvents.Event.ACTIVITY_RESUMED)pkg=event.getPackageName();}done.accept(result(call,pkg.isEmpty()?"unconfirmed":"verified",pkg.isEmpty()?"Android не сообщил текущее приложение.":"Последнее активное приложение: "+PlayerTargets.label(context,pkg),Map.of("package",pkg)));return;}
            if(name.equals("create_note")){try(ToolsData data=new ToolsData(context)){String id=data.note((String)args.get("text"));done.accept(result(call,"verified","Заметка сохранена в WileyAI.",Map.of("id",id)));}return;}
            if(name.equals("list_reminders")){try(ToolsData data=new ToolsData(context)){var list=data.reminders();done.accept(result(call,"verified",list.isEmpty()?"Напоминаний пока нет.":reminderSummary(list),Map.of("reminders",list)));}return;}
            if(name.equals("create_reminder")){long due=AndroidTools.reminderTime(call,ZonedDateTime.now());try(ToolsData data=new ToolsData(context)){String id=data.reminder(context,(String)args.get("text"),due);done.accept(result(call,"verified","Напоминание сохранено на "+Instant.ofEpochMilli(due).atZone(ZoneId.systemDefault()).format(java.time.format.DateTimeFormatter.ofPattern("dd.MM HH:mm"))+". Android может задержать уведомление в режиме экономии.",Map.of("id",id,"due",due,"exact",false)));}return;}
            if(name.equals("get_weather")){WeatherTool.fetch((String)args.get("city"),host::active,value->done.accept(value));return;}
            Intent intent;if(name.equals("create_alarm")){intent=new Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR,(Integer)args.get("hour")).putExtra(AlarmClock.EXTRA_MINUTES,(Integer)args.get("minute")).putExtra(AlarmClock.EXTRA_MESSAGE,(String)args.getOrDefault("label","WileyAI")).putExtra(AlarmClock.EXTRA_SKIP_UI,false);}
            else if(name.equals("open_wifi_settings"))intent=new Intent(Settings.ACTION_WIFI_SETTINGS);
            else if(name.equals("open_bluetooth_settings"))intent=new Intent(Settings.ACTION_BLUETOOTH_SETTINGS);
            else if(name.equals("web_search"))intent=new Intent(Intent.ACTION_VIEW,Uri.parse("https://www.google.com/search").buildUpon().appendQueryParameter("q",(String)args.get("query")).build());
            else if(name.equals("open_calendar"))intent=new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_APP_CALENDAR);
            else throw new IllegalArgumentException();
            host.launch(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));done.accept(result(call,"requested",name.equals("create_alarm")?"Запрос передан приложению часов. Проверьте и подтвердите будильник в нём.":name.equals("web_search")?"Android принял запрос на открытие поиска в браузере.":"Android принял запрос на открытие выбранного экрана.",Map.of("verified",false)));
        }catch(Exception error){done.accept(result(call,"failed","Не удалось выполнить этот шаг. Проверьте разрешения, аргументы и доступность приложения.",Map.of()));}
    }
    private static String reminderSummary(List<Map<String,Object>> reminders){List<String> items=new ArrayList<>();for(Map<String,Object> item:reminders){if(items.size()==5)break;items.add(Instant.ofEpochMilli((Long)item.get("due")).atZone(ZoneId.systemDefault()).format(java.time.format.DateTimeFormatter.ofPattern("dd.MM HH:mm"))+": "+item.get("text"));}return String.join("; ",items)+(reminders.size()>5?". Остальные — в разделе «Мои заметки и напоминания».":".");}
    private record MediaSnapshot(MediaSession.Token token,String identity,int state,long position){}
    private MediaSnapshot mediaSnapshot(String target){try{
        List<MediaController> sessions=new ArrayList<>(PlayerControl.sessions(context));
        if(!target.isEmpty()){String pkg=PlayerTargets.packageName(context,target);sessions.removeIf(item->!item.getPackageName().equals(pkg));}
        List<MediaController> playing=new ArrayList<>();for(MediaController item:sessions)if(item.getPlaybackState()!=null&&item.getPlaybackState().getState()==PlaybackState.STATE_PLAYING)playing.add(item);if(!playing.isEmpty())sessions=playing;
        Set<String> packages=new HashSet<>();for(MediaController item:sessions)packages.add(item.getPackageName());if(sessions.isEmpty()||packages.size()!=1)return null;
        MediaController controller=sessions.get(0);PlaybackState state=controller.getPlaybackState();if(state==null)return null;MediaMetadata metadata=controller.getMetadata();String id=metadata==null?"":metadata.getString(MediaMetadata.METADATA_KEY_MEDIA_ID);
        if(id==null||id.isEmpty()){String title=metadata==null?null:metadata.getString(MediaMetadata.METADATA_KEY_TITLE),artist=metadata==null?null:metadata.getString(MediaMetadata.METADATA_KEY_ARTIST);id=title==null||title.isEmpty()?"":title+"|"+(artist==null?"":artist);}
        return new MediaSnapshot(controller.getSessionToken(),id,state.getState(),state.getPosition());
    }catch(RuntimeException error){return null;}}
    private boolean mediaConfirmed(String target,String verb,MediaSnapshot before){MediaSnapshot after=mediaSnapshot(target);if(after==null)return false;
        if(verb.equals("status"))return true;if(verb.equals("play"))return after.state()==PlaybackState.STATE_PLAYING;if(verb.equals("pause"))return after.state()==PlaybackState.STATE_PAUSED;
        if(before==null||!before.token().equals(after.token()))return false;boolean changed=!after.identity().isEmpty()&&!after.identity().equals(before.identity());
        boolean restarted=verb.equals("previous")&&!after.identity().isEmpty()&&after.identity().equals(before.identity())&&before.position()>3000&&after.position()>=0&&after.position()<=1500&&(after.state()==PlaybackState.STATE_PLAYING||after.state()==PlaybackState.STATE_PAUSED);
        return (verb.equals("next")||verb.equals("previous"))&&(changed||restarted);
    }

}
