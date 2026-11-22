package ru.wildlik.wileyai.mobile;

import android.app.ActivityManager;
import android.content.*;
import android.content.res.Configuration;
import java.io.IOException;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Application-scoped cache; no Activity, prompt or listener is retained when a request ends. */
final class LocalLlmRuntime implements ComponentCallbacks2 {
    private static LocalLlmRuntime instance;
    private final Context app;
    final LocalModelSession session;
    private LocalLlmRuntime(Context context) {
        app=context.getApplicationContext();
        session=new LocalModelSession(new LocalModelSession.Backend(){
            public long create()throws IOException{return LocalLlmNative.create();}
            public void load(long h,String path)throws IOException{LocalLlmNative.load(h,path);}
            public void prepare(long h)throws IOException{LocalLlmNative.prepare(h);}
            public void grammar(long h,byte[] g)throws IOException{LocalLlmNative.grammar(h,g);}
            public void begin(long h,byte[] p)throws IOException{LocalLlmNative.begin(h,p);}
            public byte[] next(long h)throws IOException{return LocalLlmNative.next(h);}
            public long[] timings(long h){return LocalLlmNative.timings(h);}
            public void finish(long h){LocalLlmNative.finish(h);}
            public void cancel(long h){LocalLlmNative.cancel(h);}
            public void close(long h){LocalLlmNative.close(h);}
        },()->memory(app),idleMillis(),metrics->{android.util.Log.i("WileyLlm",metrics.safeLine());
            if(!"unloaded".equals(metrics.result())){
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_COLD,metrics.cold()?1:0);
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_LOAD_MS,(long)metrics.loadMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_CONTEXT_MS,(long)metrics.contextMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_PROMPT_MS,(long)metrics.promptMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_QUEUE_MS,(long)metrics.queueMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_TOKENIZE_MS,(long)metrics.tokenizeMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_PREFILL_MS,(long)metrics.prefillMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_DECODE_MS,(long)metrics.decodeMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_OUTCOME,"completed".equals(metrics.result())?0:"stopped".equals(metrics.result())?1:2);
                if(metrics.cancellationReason()!=0)DiagnosticLog.event(DiagnosticJournal.Event.MODEL_STOP_REASON,metrics.cancellationReason());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_FIRST_MS,(long)metrics.firstTokenMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_GENERATION_MS,(long)metrics.generationMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_TOTAL_MS,(long)metrics.totalMs());
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_RAM_BEFORE_MB,metrics.ramBefore()<0?-1:metrics.ramBefore()/1048576);
                DiagnosticLog.event(DiagnosticJournal.Event.MODEL_RAM_AFTER_MB,metrics.ramAfter()<0?-1:metrics.ramAfter()/1048576);
            }
        });
        app.registerComponentCallbacks(this);
    }
    static synchronized LocalLlmRuntime get(Context context) { if(instance==null)instance=new LocalLlmRuntime(context);return instance; }
    static synchronized void releaseIfCreated(String reason) { if(instance!=null)instance.session.release(reason,false); }
    static LocalModelSession.Memory memory(Context context)throws IOException {
        ActivityManager manager=(ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
        if(manager==null)throw new IOException("Не удалось проверить свободную память телефона");
        ActivityManager.MemoryInfo m=new ActivityManager.MemoryInfo();manager.getMemoryInfo(m);
        return new LocalModelSession.Memory(m.availMem,m.totalMem,m.lowMemory);
    }
    static LocalModelSession.Model model(Path path)throws IOException {
        Path real=path.toRealPath();
        return new LocalModelSession.Model(real+"|"+Files.size(real)+"|"+Files.getLastModifiedTime(real).toMillis(),real.toString());
    }
    long idleMillis() {
        String profile=app.getSharedPreferences("wiley-mobile",Context.MODE_PRIVATE).getString("llm_memory_profile","balanced");
        return switch(profile){case "eco"->60000;case "quality"->900000;default->300000;};
    }
    void profileChanged() { session.idleTimeout(idleMillis()); }
    void probe(Path path,AtomicBoolean cancelled)throws Exception { session.probe(model(path),cancelled); }
    String diagnostic() { LocalModelSession.Metrics last=session.latest();return last==null?"Генераций ещё не было. Профиль: "+idleMillis()/60000+" мин.":last.safeLine(); }
    @Override public void onTrimMemory(int level) {
        if(level==TRIM_MEMORY_UI_HIDDEN)session.release("background",false);
        else if(level>=TRIM_MEMORY_RUNNING_LOW)session.release("memory_pressure",true);
    }
    @Override public void onLowMemory() { session.release("low_memory",true); }
    @Override public void onConfigurationChanged(Configuration configuration) {}
}
