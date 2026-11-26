package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;

/** Preserve the legacy default on upgrades that never saved an explicit phrase. */
final class WakeSettings {
    static final String PREFS = "wiley-mobile";
    static final String KEY_WAKE_ENGINE = "wake_engine";
    static final String KEY_LIVEKIT_THRESHOLD = "wake_livekit_threshold";
    static final int ENGINE_VOSK = 0;
    static final int ENGINE_LIVEKIT_V2 = 1;
    static final int ENGINE_LIVEKIT_V2_CAM = 2;
    static final float DEFAULT_LIVEKIT_THRESHOLD = 0.98f;

    static void initializeNewInstall(Context context) {
        var settings = prefs(context);
        if (!settings.contains("wake_phrase") && defaultPhrase(context).equals(WakePhrase.SHORT)) {
            settings.edit().putString("wake_phrase", WakePhrase.SHORT).apply();
        }
    }

    static String defaultPhrase(Context context) {
        try {
            var info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return info.firstInstallTime == info.lastUpdateTime ? WakePhrase.SHORT : WakePhrase.DEFAULT;
        } catch (Exception unavailable) {
            return WakePhrase.DEFAULT;
        }
    }

    static int wakeEngine(Context context) {
        int raw = prefs(context).getInt(KEY_WAKE_ENGINE, ENGINE_VOSK);
        if (raw < ENGINE_VOSK || raw > ENGINE_LIVEKIT_V2_CAM) return ENGINE_VOSK;
        return raw;
    }

    static void setWakeEngine(Context context, int engine) {
        int clamped = (engine < ENGINE_VOSK || engine > ENGINE_LIVEKIT_V2_CAM) ? ENGINE_VOSK : engine;
        prefs(context).edit()
                .putInt(KEY_WAKE_ENGINE, clamped)
                .putBoolean(OwnerSpeakerFilter.KEY_ENABLED, clamped == ENGINE_LIVEKIT_V2_CAM)
                .apply();
    }

    static float liveKitThreshold(Context context) {
        float raw = prefs(context).getFloat(KEY_LIVEKIT_THRESHOLD, DEFAULT_LIVEKIT_THRESHOLD);
        if (!Float.isFinite(raw)) return DEFAULT_LIVEKIT_THRESHOLD;
        return Math.max(0.90f, Math.min(0.995f, raw));
    }

    static void setLiveKitThreshold(Context context, float value) {
        float clamped = Float.isFinite(value) ? Math.max(0.90f, Math.min(0.995f, value)) : DEFAULT_LIVEKIT_THRESHOLD;
        prefs(context).edit().putFloat(KEY_LIVEKIT_THRESHOLD, clamped).apply();
    }

    static String wakeEngineLabel(int engine) {
        return switch (engine) {
            case ENGINE_LIVEKIT_V2 -> "LiveKit C v2 · эксперимент";
            case ENGINE_LIVEKIT_V2_CAM -> "LiveKit C v2 + CAM++ · эксперимент";
            default -> "Vosk · резервный";
        };
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private WakeSettings() {}
}
