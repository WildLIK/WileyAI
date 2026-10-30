package ru.wildlik.wileyai.mobile;

import android.content.*;
import android.content.pm.ResolveInfo;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** Reads only launcher-visible activities in the current Android profile. */
final class AppCatalog {
    private final Context context;
    private final SharedPreferences preferences;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean scanning = new AtomicBoolean();
    private volatile boolean closed, scanAgain;
    private volatile List<AppRegistry.App> entries = Collections.emptyList();
    private volatile String status = "Читаю названия приложений…";
    private final Runnable changed;
    private boolean registered;
    private final BroadcastReceiver packages = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { refresh(); }
    };
    AppCatalog(Context context, SharedPreferences preferences, Runnable changed) {
        this.context = context.getApplicationContext(); this.preferences = preferences; this.changed = changed;
        IntentFilter filter = new IntentFilter(); filter.addAction(Intent.ACTION_PACKAGE_ADDED); filter.addAction(Intent.ACTION_PACKAGE_REMOVED); filter.addAction(Intent.ACTION_PACKAGE_REPLACED); filter.addAction(Intent.ACTION_PACKAGE_CHANGED); filter.addDataScheme("package");
        try {
            if (Build.VERSION.SDK_INT >= 33) this.context.registerReceiver(packages, filter, Context.RECEIVER_NOT_EXPORTED);
            else this.context.registerReceiver(packages, filter);
            registered = true;
        } catch (RuntimeException ignored) { /* Manual refresh remains available. */ }
        refresh();
    }
    List<AppRegistry.App> entries() { return entries; }
    String status() { return status; }
    boolean scanning() { return scanning.get(); }
    private void post(Runnable callback) { main.post(() -> { if (!closed) callback.run(); }); }
    void refresh() {
        if (closed) return;
        if (!scanning.compareAndSet(false, true)) { scanAgain = true; return; }
        status = "Обновляю названия приложений…"; post(changed);
        worker.execute(() -> {
            try {
                List<ResolveInfo> available = context.getPackageManager().queryIntentActivities(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0);
                List<AppRegistry.App> snapshot = new ArrayList<>(); Set<String> ids = new HashSet<>();
                for (ResolveInfo app : available) {
                    if (closed) return;
                    if (app.activityInfo == null || !app.activityInfo.enabled || !app.activityInfo.exported || !app.activityInfo.applicationInfo.enabled) continue;
                    String id = new ComponentName(app.activityInfo.packageName, app.activityInfo.name).flattenToString();
                    if (!ids.add(id)) continue;
                    try {
                        String label = app.loadLabel(context.getPackageManager()).toString().trim();
                        if (label.isEmpty()) label = app.activityInfo.packageName;
                        Set<String> saved = preferences.getStringSet("app_names:" + id, Collections.emptySet());
                        snapshot.add(new AppRegistry.App(id, label, app.activityInfo.packageName, app.activityInfo.name, Collections.unmodifiableList(new ArrayList<>(saved))));
                    } catch (RuntimeException unavailable) { /* Skip an activity removed during the scan. */ }
                }
                snapshot.sort(Comparator.comparing(AppRegistry.App::label, String.CASE_INSENSITIVE_ORDER).thenComparing(AppRegistry.App::id));
                entries = Collections.unmodifiableList(snapshot);
                status = "Приложений с экраном запуска: " + snapshot.size() + " · обновлено " + new java.text.SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date());
            } catch (RuntimeException error) { status = "Не удалось обновить список приложений. Попробуйте обновить ещё раз."; }
            finally {
                scanning.set(false); post(changed);
                if (scanAgain && !closed) { scanAgain = false; refresh(); }
            }
        });
    }
    void resolve(String name, Consumer<List<AppRegistry.App>> callback) {
        if (closed) return;
        worker.execute(() -> {
            String normalized = SpokenNames.app(name);
            String role = normalized.matches("музык[ау]|плеер|музыкальное приложение") ? "music" : normalized.matches("telegram|мессенджер") ? "messenger" : normalized.equals("youtube") ? "video" : "";
            String selected = preferences.getString("preferred_" + role, "");
            List<AppRegistry.App> matches = new ArrayList<>();
            if (!role.isEmpty() && !selected.isEmpty()) { for (AppRegistry.App app : entries) if (app.id().equals(selected)) matches.add(app); }
            else matches = AppRegistry.resolve(entries, name);
            List<AppRegistry.App> result = matches; post(() -> callback.accept(result));
        });
    }
    String preferredLabel(String role) { String selected = preferences.getString("preferred_" + role, ""); for (AppRegistry.App app : entries) if (app.id().equals(selected)) return app.label(); return selected.isEmpty() ? "Выбрать приложение" : "Приложение удалено — выберите другое"; }
    void preferred(String role, AppRegistry.App app) { preferences.edit().putString("preferred_" + role, app == null ? "" : app.id()).apply(); post(changed); }
    void saveAliases(AppRegistry.App app, List<String> aliases, Consumer<Boolean> result) {
        if (closed) return;
        worker.execute(() -> {
            boolean saved = preferences.edit().putStringSet("app_names:" + app.id(), new LinkedHashSet<>(aliases)).commit();
            if (saved) {
                List<AppRegistry.App> updated = new ArrayList<>();
                for (AppRegistry.App entry : entries) updated.add(entry.id().equals(app.id()) ? new AppRegistry.App(entry.id(), entry.label(), entry.packageName(), entry.activity(), Collections.unmodifiableList(new ArrayList<>(aliases))) : entry);
                entries = Collections.unmodifiableList(updated); refresh(); post(() -> result.accept(true));
            }
            else { status = "Не удалось сохранить названия приложения. Проверьте свободное место."; post(changed); post(() -> result.accept(false)); }
        });
    }
    void close() { closed = true; if (registered) { context.unregisterReceiver(packages); registered = false; } worker.shutdown(); }
}
