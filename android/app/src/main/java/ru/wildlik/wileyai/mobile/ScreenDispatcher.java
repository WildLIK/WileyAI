package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** Only explicit requests can read the screen. Model proposals are never executed unchecked. */
final class ScreenDispatcher {
    private static final ExecutorService WORKER=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"screen-local-model");t.setDaemon(true);return t;});
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static BrainProvider.Cancellation pending;
    static synchronized void cancel(){if(pending!=null){pending.cancel();pending=null;}}
    private static synchronized boolean live(BrainProvider.Cancellation c){return pending==c&&!c.cancelled();}
    private static synchronized void finish(BrainProvider.Cancellation c){if(pending==c)pending=null;}
    static boolean dispatch(Context context,AppCatalog apps,String request,BooleanSupplier active,Consumer<String> result){
        return dispatch(context,apps,request,active,false,result);
    }
    static boolean dispatch(Context context,AppCatalog apps,String request,BooleanSupplier active,boolean voiceOverlay,Consumer<String> result){
        ScreenRequest.Kind kind=ScreenRequest.classify(request,available(context));
        if(kind==ScreenRequest.Kind.NONE)return false;
        cancel();
        // Observational only: records statuses and counts, never the request text or screen content.
        VoiceDiagnostics.route(kind.toString(), "маршрутизатор экрана", kind == ScreenRequest.Kind.ACTION_REFUSED ? "нажатия недоступны" : "");
        if(kind==ScreenRequest.Kind.ACTION_REFUSED){result.accept("Пока я могу только наблюдать экран; нажатия, ввод и прокрутка недоступны.");return true;}
        Context app=context.getApplicationContext();
        AndroidToolExecutor.Host host=new AndroidToolExecutor.Host(){
            public boolean active(){return active.getAsBoolean();}
            public boolean screenAuthorized(){return active()&&ScreenRequest.classify(request)==kind;}
            public boolean voiceOverlay(){return voiceOverlay;}
            public void launch(Intent unused){throw new IllegalStateException("Screen observation is read-only");}
        };
        AndroidTools.Call observe=new AndroidTools.Call("screen_observe",Map.of());
        AndroidToolExecutor executor=new AndroidToolExecutor(app,apps);
        executor.execute(observe,host,value->{
            VoiceDiagnostics.observation("проекция", outcome(value), matches(value.data()), target(value.data()));
            if(!value.status().equals("verified")){if(active.getAsBoolean())result.accept(value.summary());return;}
            List<ScreenContextMatcher.Candidate> matched=kind==ScreenRequest.Kind.FIND?ScreenContextMatcher.match(request,labels(value.data())):List.of();
            if(kind==ScreenRequest.Kind.FIND&&!matched.isEmpty()&&ScreenContextMatcher.ambiguous(matched)){
                ScreenContextMatcher.record(new ScreenContextMatcher.Correction(request,ScreenContextMatcher.query(request),"фонетическое совпадение неоднозначно",names(matched),"","уточнение"));
                if(active.getAsBoolean())result.accept("На экране есть похожие подписи: "+named(matched.subList(0,2))+". Уточните, какую искать.");
                return;
            }
            boolean matchedSingle=kind==ScreenRequest.Kind.FIND&&!matched.isEmpty();
            if(matchedSingle)ScreenContextMatcher.record(new ScreenContextMatcher.Correction(request,ScreenContextMatcher.query(request),"фонетический скелет согласных",names(matched),matched.get(0).label(),"screen_find"));
            BrainProvider.Cancellation token=new BrainProvider.Cancellation();synchronized(ScreenDispatcher.class){pending=token;}
            Runnable poll=new Runnable(){public void run(){if(!live(token))return;if(!valid(app,value.data(),host,observe,false)){cancel();if(active.getAsBoolean())result.accept("Экран изменился или разрешение отозвано. Повторите запрос при необходимости.");return;}MAIN.postDelayed(this,250);}};
            MAIN.postDelayed(poll,250);
            if(matchedSingle){
                // Confident phonetic match resolves the label without the model; screen_find re-reads
                // the same anchored window with its own permission checks, so no stale snapshot is used.
                String label=matched.get(0).label();
                AndroidTools.Call find=new AndroidTools.Call("screen_find",Map.of("query",label));
                executor.execute(find,host,found->{
                    VoiceDiagnostics.observation("поиск элемента", outcome(found), matches(found.data()), target(found.data()));
                    finish(token);
                    if(!active.getAsBoolean())return;
                    if(!valid(app,value.data(),host,observe,false)){result.accept("Экран изменился или разрешение отозвано. Повторите запрос при необходимости.");return;}
                    result.accept("Похоже, «"+ScreenContextMatcher.query(request)+"» — это «"+label+"» на экране. "+found.summary());
                });
                return;
            }
            WORKER.execute(()->{
                ScreenModelGate.Decision decision=null;
                try(LocalProvider provider=new LocalProvider(app)){
                    if(valid(app,value.data(),host,observe)&&live(token))decision=ScreenModelGate.decide(provider,request,kind,value.data(),token);
                }catch(Exception ignored){}
                ScreenModelGate.Decision answer=decision;
                MAIN.post(()->{
                    if(!live(token))return;
                    if(!valid(app,value.data(),host,observe)){finish(token);if(active.getAsBoolean())result.accept("Экран изменился или разрешение отозвано. Повторите запрос при необходимости.");return;}
                    finish(token);
                    if(answer==null||!answer.accepted()){result.accept("Не удалось уверенно определить ответ по доступной части экрана. Попробуйте уточнить запрос.");return;}
                    if(kind==ScreenRequest.Kind.OBSERVE){result.accept(value.summary());return;}
                    // A fresh, separately permission-checked read confirms the chosen label.
                    AndroidTools.Call find=new AndroidTools.Call("screen_find",Map.of("query",answer.label()));
                    executor.execute(find,host,found->{
                        VoiceDiagnostics.observation("поиск элемента", outcome(found), matches(found.data()), target(found.data()));
                        if(active.getAsBoolean())result.accept(found.summary());
                    });
                });
            });
        });
        return true;
    }
    private static String outcome(AndroidTools.Result result) {
        return switch (result.status()) {
            case "verified" -> "успешно";
            case "unavailable" -> "служба или исходное окно недоступны";
            case "permission_required" -> "нет разрешения или отключено в настройках";
            case "protected" -> "экран защищён или приложение не разрешено";
            case "cancelled" -> "окно изменилось или запрос отменён";
            case "partial" -> "проекция ограничена";
            case "needs_input" -> "требуется уточнение";
            case "rate_limited" -> "слишком частые запросы";
            default -> result.status();
        };
    }
    private static int matches(Map<String,Object> data) {
        Object matches = data.get("matches");
        return matches instanceof Integer count ? count : 0;
    }
    private static String target(Map<String,Object> data) {
        Object detail = data.get("detail"), pkg = data.get("package");
        return pkg instanceof String name ? name : detail instanceof String code ? code : "";
    }
    private static List<String> labels(Map<String,Object> data){
        Object raw=data.get("elements");
        if(!(raw instanceof List<?> elements))return List.of();
        java.util.LinkedHashSet<String> out=new java.util.LinkedHashSet<>();
        for(Object item:elements) if(item instanceof Map<?,?> element){
            for(String key:new String[]{"text","description"}){
                Object value=element.get(key);
                if(value instanceof String text&&!text.isEmpty())out.add(text);
            }
        }
        return new ArrayList<>(out);
    }
    private static List<String> names(List<ScreenContextMatcher.Candidate> candidates){
        List<String> names=new ArrayList<>();
        for(ScreenContextMatcher.Candidate candidate:candidates)names.add(candidate.label());
        return names;
    }
    private static String named(List<ScreenContextMatcher.Candidate> candidates){
        List<String> names=new ArrayList<>();
        for(ScreenContextMatcher.Candidate candidate:candidates)names.add("«"+candidate.label()+"»");
        return String.join(", ",names);
    }
    private static boolean valid(Context c,Map<String,Object> data,AndroidToolExecutor.Host host,AndroidTools.Call call){
        return valid(c,data,host,call,true);
    }
    private static boolean valid(Context c,Map<String,Object> data,AndroidToolExecutor.Host host,AndroidTools.Call call,boolean verifyContent){
        return ToolPermissionManager.denied(c,call).isEmpty()&&ScreenObservationService.current(c,data,host,verifyContent);
    }
    /** Observation is offered as the read-only answer to an ambiguous find request only when it is fully available. */
    private static boolean available(Context context){
        if(!ScreenObservationService.running()||!context.getSharedPreferences("wiley-mobile",0).getBoolean("screen_observation_enabled",false))return false;
        ModelManager models=new ModelManager(context);return models.toolsAllowed()&&models.selected()==BrainProvider.Kind.LOCAL;
    }
    private ScreenDispatcher(){}
}
