package ru.wildlik.wileyai.mobile;

import android.accessibilityservice.AccessibilityService;
import android.content.Context;
import android.graphics.Rect;
import android.os.Build;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/** Observes on demand; never stores a node or an event and never performs actions. */
public final class ScreenObservationService extends AccessibilityService {
    private static volatile ScreenObservationService active;
    private final AtomicLong revision=new AtomicLong();
    private volatile long anchorWindowId=-1;
    private volatile String anchorPackage;
    private long lastRequest;
    static boolean running(){return active!=null;}
    static boolean enabled(Context context){
        android.view.accessibility.AccessibilityManager manager=(android.view.accessibility.AccessibilityManager)context.getSystemService(Context.ACCESSIBILITY_SERVICE);
        if(manager==null)return false;
        for(android.accessibilityservice.AccessibilityServiceInfo info:manager.getEnabledAccessibilityServiceList(android.accessibilityservice.AccessibilityServiceInfo.FEEDBACK_ALL_MASK)){
            android.content.pm.ResolveInfo resolved=info.getResolveInfo();if(resolved==null)continue;
            android.content.pm.ServiceInfo service=resolved.serviceInfo;
            if(service!=null&&context.getPackageName().equals(service.packageName)&&ScreenObservationService.class.getName().equals(service.name))return true;
        }
        return false;
    }
    @Override public void onServiceConnected(){super.onServiceConnected();active=this;revision.incrementAndGet();}
    @Override public void onAccessibilityEvent(AccessibilityEvent event){
        revision.incrementAndGet();
        if(event==null||event.getEventType()!=AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED)return;
        CharSequence name=event.getClassName(),pkg=event.getPackageName();
        // Only activity transitions anchor the screen the user came from; voice panels, dialogs and popups never do.
        if(name!=null&&pkg!=null&&name.toString().endsWith("Activity")){anchorWindowId=event.getWindowId();anchorPackage=pkg.toString();}
    }
    @Override public void onInterrupt(){revision.incrementAndGet();}
    @Override public void onDestroy(){revision.incrementAndGet();if(active==this)active=null;super.onDestroy();}
    /** Do not inspect the voice panel and never guess between application windows. */
    private static AccessibilityNodeInfo targetRoot(ScreenObservationService service,AndroidToolExecutor.Host host){
        if(!host.voiceOverlay())return service.getRootInActiveWindow();
        List<AccessibilityWindowInfo> windows=service.getWindows();
        if(windows==null)return null;
        try{
            String own=service.getPackageName();
            long anchor=service.anchorWindowId;String anchorPackage=service.anchorPackage;
            boolean anchored=anchorPackage!=null&&anchor>=0;
            AccessibilityWindowInfo match=null,only=null;int candidates=0;
            for(AccessibilityWindowInfo window:windows){
                if(window.getType()!=AccessibilityWindowInfo.TYPE_APPLICATION)continue;
                AccessibilityNodeInfo probe=window.getRoot();
                if(probe==null)continue;
                if(!probe.isVisibleToUser()){probe.recycle();continue;} // Occluded background windows are not what the user asked about.
                CharSequence name=probe.getPackageName();probe.recycle();
                if(name==null)continue;
                String pkg=name.toString();
                if(anchored){
                    if(window.getId()==anchor&&anchorPackage.equals(pkg)){match=window;break;}
                    continue;
                }
                if(pkg.equals(own))continue; // The voice panel, our dialogs and our own activity are never the requested screen.
                if(++candidates>1)break; // Split-screen or several application windows: no guess.
                only=window;
            }
            AccessibilityWindowInfo selected=match!=null?match:!anchored&&candidates==1?only:null;
            return selected==null?null:selected.getRoot();
        }finally{for(AccessibilityWindowInfo window:windows)window.recycle();}
    }
    static boolean current(Context context,Map<String,Object> snapshot,AndroidToolExecutor.Host host){
        return current(context,snapshot,host,true);
    }
    static boolean current(Context context,Map<String,Object> snapshot,AndroidToolExecutor.Host host,boolean verifyContent){
        ScreenObservationService service=active;AccessibilityNodeInfo root=null;
        if(service==null||!host.active()||!host.screenAuthorized()||!context.getSharedPreferences("wiley-mobile",0).getBoolean("screen_observation_enabled",false))return false;
        try{
            String pkg=(String)snapshot.get("package");
            if(!ScreenAppPermissions.allowed(context,pkg))return false;
            root=targetRoot(service,host);
            if(root==null||!Objects.equals(snapshot.get("window_id"),root.getWindowId())||!Objects.equals(pkg,String.valueOf(root.getPackageName()))||service!=active||!host.active()||!host.screenAuthorized())return false;
            // A third-party app may change its tree without emitting an event.
            // Always re-read before sending data to the model or returning a result.
            if(!verifyContent)return true;
            String identity=ScreenPrivacy.trustedPackage(pkg,context.getPackageName())?"":ScreenAppPermissions.identity(context,pkg);
            // Accessibility events from unrelated windows (including WileyAI's own panel) must not cancel a read;
            // an actual tree change is caught below by comparing both full reads.
            java.util.function.BooleanSupplier allowed=()->active==service&&host.active()&&host.screenAuthorized()&&context.getSharedPreferences("wiley-mobile",0).getBoolean("screen_observation_enabled",false)&&ScreenAppPermissions.stillAllowed(context,pkg,identity);
            Collector fresh=new Collector(allowed);fresh.visit(root,0,-1);
            if(fresh.cancelled||fresh.protectedScreen||fresh.truncated||!allowed.getAsBoolean())return false;
            Object raw=snapshot.get("elements");if(!(raw instanceof List<?> old)||old.size()!=fresh.elements.size())return false;
            for(int i=0;i<old.size();i++){if(!(old.get(i) instanceof Map<?,?> item))return false;Map<Object,Object> original=new LinkedHashMap<>(item);original.remove("id");if(!original.equals(fresh.elements.get(i)))return false;}
            return allowed.getAsBoolean()&&ScreenAppPermissions.allowed(context,pkg);
        }catch(Exception ignored){return false;}finally{if(root!=null)root.recycle();}
    }
    private static AndroidTools.Result answer(AndroidTools.Call call,String status,String text,Map<String,Object> data){return new AndroidTools.Result(call.tool(),status,text,data);}
    static AndroidTools.Result observe(Context context,AndroidTools.Call call,AndroidToolExecutor.Host host){
        ScreenObservationService service=active;
        if(service==null)return answer(call,"unavailable","Служба наблюдения недоступна. Включите её вручную в специальных возможностях Android.",Map.of("detail","service_missing"));
        if(!host.active()||!host.screenAuthorized())return answer(call,"cancelled","Наблюдение отменено.",Map.of());
        if(!context.getSharedPreferences("wiley-mobile",0).getBoolean("screen_observation_enabled",false))return answer(call,"permission_required","Включите наблюдение экрана в инструментах WileyAI.",Map.of());
        long now=SystemClock.elapsedRealtime();synchronized(service){if(now-service.lastRequest<1000)return answer(call,"rate_limited","Повторите запрос через секунду.",Map.of());service.lastRequest=now;}
        long version=service.revision.get();AccessibilityNodeInfo root=null,verify=null;
        try{
            root=targetRoot(service,host);if(root==null)return answer(call,"unavailable","Не удалось однозначно определить исходное окно приложения. Откройте нужное приложение и повторите запрос.",Map.of("detail","ambiguous_window"));
            String pkg=root.getPackageName()==null?null:root.getPackageName().toString();
            if(!ScreenAppPermissions.allowed(context,pkg))return answer(call,"protected","Для этого приложения нет разрешения или окно может быть чувствительным.",Map.of("detail","app_permission"));
            String identity=ScreenPrivacy.trustedPackage(pkg,context.getPackageName())?"":ScreenAppPermissions.identity(context,pkg);
            if(pkg.equals("com.android.settings")){
                android.content.pm.ApplicationInfo app=context.getPackageManager().getApplicationInfo(pkg,0);
                if((app.flags&(android.content.pm.ApplicationInfo.FLAG_SYSTEM|android.content.pm.ApplicationInfo.FLAG_UPDATED_SYSTEM_APP))==0)return answer(call,"protected","Не удалось подтвердить системное окно.",Map.of());
            }
            java.util.function.BooleanSupplier allowed=()->host.active()&&host.screenAuthorized()&&context.getSharedPreferences("wiley-mobile",0).getBoolean("screen_observation_enabled",false)&&ScreenAppPermissions.stillAllowed(context,pkg,identity)&&active==service;
            Collector c=new Collector(allowed);c.visit(root,0,-1);
            if(c.cancelled)return answer(call,"cancelled","Наблюдение отменено или экран изменился.",Map.of("detail","cancelled"));
            if(c.protectedScreen)return answer(call,"protected","Экран содержит защищённые поля; содержимое не читается.",Map.of());
            if(c.truncated)return answer(call,"partial","Дерево слишком велико или неполно для безопасной проверки.",Map.of("truncated",true));
            verify=targetRoot(service,host);
            if(!host.active()||!host.screenAuthorized()||!context.getSharedPreferences("wiley-mobile",0).getBoolean("screen_observation_enabled",false)||active!=service||verify==null||root.getWindowId()!=verify.getWindowId()||!Objects.equals(root.getPackageName(),verify.getPackageName()))return answer(call,"cancelled","Экран изменился или запрос отменён; повторите его.",Map.of("detail","window_changed"));
            Collector current=new Collector(allowed);current.visit(verify,0,-1);
            if(current.cancelled||current.protectedScreen||current.truncated||!c.elements.equals(current.elements)||!allowed.getAsBoolean()||!ScreenAppPermissions.allowed(context,pkg))return answer(call,"cancelled","Экран изменился, разрешение отозвано или запрос отменён.",Map.of("detail","window_changed_or_revoked"));
            int bytes=512;for(Map<String,Object> element:c.elements){bytes+=240;for(Object value:element.values())bytes+=String.valueOf(value).getBytes(java.nio.charset.StandardCharsets.UTF_8).length;}
            if(bytes>8192)return answer(call,"partial","Дерево слишком велико для безопасной передачи.",Map.of("truncated",true));
            String original=call.tool().equals("screen_find")?((String)call.arguments().get("query")).toLowerCase(Locale.ROOT):"";
            String query=call.tool().equals("screen_find")?ScreenPrivacy.query(original):"";
            if(call.tool().equals("screen_find")&&query.isEmpty())return answer(call,"needs_input","Уточните элемент: например, поиск, настройки или продолжить.",Map.of());
            boolean wantsField=original.matches("(?s).*(?:поле|строк[ауи]).*");
            boolean wantsButton=original.matches("(?s).*(?:кнопк|button).*");
            List<Map<String,Object>> selected=new ArrayList<>();for(Map<String,Object> e:c.elements){
                if(wantsField&&!Boolean.TRUE.equals(e.get("editable")))continue;
                if(wantsButton&&!Boolean.TRUE.equals(e.get("clickable")))continue;
                if(query.isEmpty()||ScreenPrivacy.matches((String)e.get("text"),query)||ScreenPrivacy.matches((String)e.get("description"),query))selected.add(e);
            }
            String id=UUID.randomUUID().toString();int n=0;for(Map<String,Object> item:selected)item.put("id",id+":"+(++n));
            String text;if(call.tool().equals("screen_find")){
                text=selected.isEmpty()?"В доступной части дерева элемент не найден.":"Найдено совпадений: "+selected.size()+". "+summarize(selected);
                if(selected.size()==1){Map<String,Object> element=selected.get(0);text+=". Границы на экране: "+element.get("bounds")+" пикселей; "+(Boolean.TRUE.equals(element.get("enabled"))?"элемент доступен":"элемент недоступен")+".";}
                else if(selected.size()>1)text+=". Уточните нужный элемент.";
            }
            else text=selected.isEmpty()?"Android предоставил дерево, но знакомые безопасные элементы не найдены.":"Вижу элементы: "+summarize(selected)+". Показана только безопасная часть экрана.";
            return answer(call,"verified",text,Map.of("package",pkg,"window_id",root.getWindowId(),"revision",version,"snapshot_id",id,"timestamp",System.currentTimeMillis(),"tree_quality","partial","elements",selected,"matches",selected.size()));
        }catch(Exception problem){return answer(call,"unavailable","Android не предоставил безопасный снимок окна.",Map.of("detail","no_snapshot"));}
        finally{if(verify!=null)verify.recycle();if(root!=null)root.recycle();}
    }
    private static String summarize(List<Map<String,Object>> list){List<String> out=new ArrayList<>();for(Map<String,Object> e:list){if(out.size()==8)break;String text=(String)e.get("text");if(text.isEmpty())text=(String)e.get("description");if(text.isEmpty())text=Boolean.TRUE.equals(e.get("editable"))?"поле ввода":"элемент без подписи";out.add(text);}return String.join(", ",out)+(list.size()>8?" и ещё "+(list.size()-8):"");}
    private static final class Collector {
        int visited;boolean truncated,protectedScreen,cancelled;final long deadline=SystemClock.elapsedRealtime()+250;final java.util.function.BooleanSupplier allowed;final List<Map<String,Object>> elements=new ArrayList<>();
        Collector(java.util.function.BooleanSupplier allowed){this.allowed=allowed;}
        void visit(AccessibilityNodeInfo node,int depth,int parent){
            if(protectedScreen||truncated||cancelled)return;
            if(!allowed.getAsBoolean()){cancelled=true;return;}
            if(SystemClock.elapsedRealtime()>deadline){truncated=true;return;}
            if(depth>12||++visited>150){truncated=true;return;}
            int type=node.getInputType();int variation=type&android.text.InputType.TYPE_MASK_VARIATION;
            if(node.isPassword()||(node.isEditable()&&(variation==android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD||variation==android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD||variation==android.text.InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD||variation==android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD))||(Build.VERSION.SDK_INT>=34&&node.isAccessibilityDataSensitive())){protectedScreen=true;return;}
            CharSequence cls=node.getClassName();String className=cls==null?"":cls.toString();
            if(ScreenPrivacy.protectedName(className)){protectedScreen=true;return;}
            if(node.isVisibleToUser()){
                // A third-party application may put an actual value even in a field's hint or description.
                CharSequence raw=node.isEditable()?null:node.getText(),description=node.isEditable()?null:node.getContentDescription();
                if(ScreenPrivacy.sensitive(raw)||ScreenPrivacy.sensitive(description)){protectedScreen=true;return;}
                String text=ScreenPrivacy.label(raw),desc=ScreenPrivacy.label(description);
                if(!text.isEmpty()||!desc.isEmpty()||node.isEditable()||node.isClickable()||node.isScrollable()){
                    if(elements.size()>=30){truncated=true;return;}
                    Rect bounds=new Rect();node.getBoundsInScreen(bounds);Map<String,Object> e=new LinkedHashMap<>();
                    e.put("text",text);e.put("description",desc);e.put("role",node.isEditable()?"field":node.isClickable()?"button":node.isScrollable()?"scrollable":"text");e.put("clickable",node.isClickable());e.put("enabled",node.isEnabled());e.put("selected",node.isSelected());e.put("scrollable",node.isScrollable());e.put("editable",node.isEditable());e.put("bounds",List.of(bounds.left,bounds.top,bounds.right,bounds.bottom));e.put("depth",depth);e.put("parent",parent);elements.add(e);parent=elements.size()-1;
                }
            }
            for(int i=0;i<node.getChildCount();i++){AccessibilityNodeInfo child=node.getChild(i);if(child==null){truncated=true;return;}try{visit(child,depth+1,parent);}finally{child.recycle();}if(protectedScreen||truncated)return;}
        }
    }
}
