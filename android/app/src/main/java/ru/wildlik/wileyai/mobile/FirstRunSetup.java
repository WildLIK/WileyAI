package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;

/** Persisted separately so reopening setup doesn't reset any feature preferences. */
final class FirstRunSetup {
    static final int LAST = 4;
    private final SharedPreferences prefs;

    FirstRunSetup(Context context) { prefs = context.getSharedPreferences("first-run-setup", Context.MODE_PRIVATE); }

    boolean shouldOpen(Context context) {
        if (prefs.getBoolean("finished", false)) return false;
        if (prefs.contains("step")) return true;
        try {
            var install = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            if (install.lastUpdateTime > install.firstInstallTime) {
                finish();
                return false;
            }
        } catch (PackageManager.NameNotFoundException ignored) { return false; }
        return true;
    }

    int step() { return Math.min(LAST, Math.max(0, prefs.getInt("step", 0))); }
    void step(int next) { prefs.edit().putInt("step", next).apply(); }
    void finish() { prefs.edit().putBoolean("finished", true).remove("step").apply(); }
}
