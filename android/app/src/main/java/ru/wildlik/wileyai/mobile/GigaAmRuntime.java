package ru.wildlik.wileyai.mobile;

import android.app.ActivityManager;
import android.content.*;
import android.content.res.Configuration;
import java.io.IOException;
import java.nio.file.Path;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;

/** Application-scoped ASR cache; no Activity, utterance or listener is retained when a request ends. */
final class GigaAmRuntime implements ComponentCallbacks2 {
    private static GigaAmRuntime instance;
    private final Context app;
    final GigaAmSession session;
    private GigaAmRuntime(Context context) {
        app = context.getApplicationContext();
        session = new GigaAmSession(new GigaAmSherpa(), () -> memory(app), idleMillis(app),
            metrics -> android.util.Log.i("WileyAsr", metrics.safeLine()));
        app.registerComponentCallbacks(this);
    }
    static synchronized GigaAmRuntime get(Context context) { if (instance == null) instance = new GigaAmRuntime(context); return instance; }
    static synchronized void releaseIfCreated(String reason) { if (instance != null) instance.session.release(reason, false); }
    /** Panel-open preload; no-op unless GigaAM is the selected engine and the model is installed. */
    static void preloadIfSelected(Context context) {
        if (context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE).getInt("asr_engine", 0) != 3) return;
        get(context).prepare();
    }
    static GigaAmSession.Memory memory(Context context) throws IOException {
        ActivityManager manager = (ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
        if (manager == null) throw new IOException("Не удалось проверить свободную память телефона");
        ActivityManager.MemoryInfo m = new ActivityManager.MemoryInfo(); manager.getMemoryInfo(m);
        return new GigaAmSession.Memory(m.availMem, m.totalMem, m.lowMemory);
    }
    static GigaAmSession.Model model(Path directory) throws IOException {
        Path real = directory.toRealPath();
        String identity = real + "|" + GigaAmModel.ENCODER.bytes();
        return new GigaAmSession.Model(identity, real.resolve(GigaAmModel.ENCODER.name()).toString(),
            real.resolve(GigaAmModel.DECODER.name()).toString(), real.resolve(GigaAmModel.JOINER.name()).toString(),
            real.resolve(GigaAmModel.TOKENS.name()).toString());
    }
    static long idleMillis(Context context) {
        String profile = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE).getString("stt_memory_profile", "balanced");
        return switch (profile) { case "eco" -> 60000L; case "quality" -> 900000L; default -> 300000L; };
    }
    void profileChanged() { session.idleTimeout(idleMillis(app)); }
    /** Model weights may be prepared before the user speaks; failures surface at recognition time. */
    void prepare() {
        try { Path active = GigaAmModelManager.activeModel(app); if (active == null) return; session.prepare(model(active)); }
        catch (IOException missing) { /* Honest error surfaces when the engine is actually used. */ }
    }
    GigaAmSession.Ticket recognize(float[] samples, int sampleRate, double audioMs) throws IOException {
        Path active = GigaAmModelManager.activeModel(app);
        if (active == null) throw new IOException("Модель GigaAM v3 не установлена. Установите её в «Компоненты → Голос → Распознавание».");
        return session.recognize(model(active), samples, sampleRate, audioMs);
    }
    CompletableFuture<Void> probe(AtomicBoolean cancel) throws IOException {
        Path active = GigaAmModelManager.activeModel(app);
        if (active == null) throw new IOException("Модель GigaAM v3 не установлена");
        return session.probe(model(active), cancel);
    }
    String diagnostic() {
        GigaAmSession.Metrics last = session.latest();
        return last == null ? "Распознаваний GigaAM ещё не было. Профиль удержания: " + idleMillis(app) / 60000 + " мин."
            : last.safeLine() + " · профиль: " + idleMillis(app) / 60000 + " мин.";
    }
    @Override public void onTrimMemory(int level) {
        if (level == TRIM_MEMORY_UI_HIDDEN) session.release("background", false);
        else if (level >= TRIM_MEMORY_RUNNING_LOW) session.release("memory_pressure", true);
    }
    @Override public void onLowMemory() { session.release("low_memory", true); }
    @Override public void onConfigurationChanged(Configuration configuration) {}
}
