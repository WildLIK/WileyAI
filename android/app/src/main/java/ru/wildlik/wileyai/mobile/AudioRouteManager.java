package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioRecordingConfiguration;
import android.media.MediaRecorder;
import android.media.audiofx.AcousticEchoCanceler;
import android.media.audiofx.NoiseSuppressor;
import android.os.Build;
import android.util.Log;
import java.util.List;

/**
 * Manages hardware AEC, NoiseSuppressor, Bluetooth SCO / communication routing, and mic contention checks.
 * Each capability has an independent rollback toggle in SharedPreferences ("wiley-mobile").
 */
final class AudioRouteManager {
    private static final String TAG = "WileyAudioRoute";
    static final String PREFS = "wiley-mobile";
    static final String KEY_AEC_ENABLED = "audio_aec_enabled";
    static final String KEY_NS_ENABLED = "audio_ns_enabled";
    static final String KEY_BT_SCO_ENABLED = "audio_bt_sco_enabled";

    static final class EffectsSession implements AutoCloseable {
        private AcousticEchoCanceler aec;
        private NoiseSuppressor ns;
        final boolean aecAttached;
        final boolean nsAttached;

        EffectsSession(int audioSessionId, boolean wantAec, boolean wantNs) {
            boolean aecOk = false;
            boolean nsOk = false;
            if (wantAec && AcousticEchoCanceler.isAvailable()) {
                try {
                    aec = AcousticEchoCanceler.create(audioSessionId);
                    if (aec != null) {
                        aec.setEnabled(true);
                        aecOk = aec.getEnabled();
                    }
                } catch (RuntimeException ignored) {
                    if (aec != null) { aec.release(); aec = null; }
                }
            }
            if (wantNs && NoiseSuppressor.isAvailable()) {
                try {
                    ns = NoiseSuppressor.create(audioSessionId);
                    if (ns != null) {
                        ns.setEnabled(true);
                        nsOk = ns.getEnabled();
                    }
                } catch (RuntimeException ignored) {
                    if (ns != null) { ns.release(); ns = null; }
                }
            }
            this.aecAttached = aecOk;
            this.nsAttached = nsOk;
        }

        @Override public void close() {
            if (aec != null) {
                try { aec.release(); } catch (RuntimeException ignored) {}
                aec = null;
            }
            if (ns != null) {
                try { ns.release(); } catch (RuntimeException ignored) {}
                ns = null;
            }
        }
    }

    static boolean isAecEnabled(Context context) {
        return prefs(context).getBoolean(KEY_AEC_ENABLED, true);
    }

    static void setAecEnabled(Context context, boolean enabled) {
        prefs(context).edit().putBoolean(KEY_AEC_ENABLED, enabled).apply();
    }

    static boolean isNsEnabled(Context context) {
        return prefs(context).getBoolean(KEY_NS_ENABLED, true);
    }

    static void setNsEnabled(Context context, boolean enabled) {
        prefs(context).edit().putBoolean(KEY_NS_ENABLED, enabled).apply();
    }

    static boolean isBtScoEnabled(Context context) {
        return prefs(context).getBoolean(KEY_BT_SCO_ENABLED, true);
    }

    static void setBtScoEnabled(Context context, boolean enabled) {
        prefs(context).edit().putBoolean(KEY_BT_SCO_ENABLED, enabled).apply();
    }

    /** Preferred AudioSource for active command/dialog capture (VOICE_COMMUNICATION enables HW AEC on most devices). */
    static int commandAudioSource(Context context) {
        if (isAecEnabled(context) && AcousticEchoCanceler.isAvailable()) {
            return MediaRecorder.AudioSource.VOICE_COMMUNICATION;
        }
        return MediaRecorder.AudioSource.VOICE_RECOGNITION;
    }

    static EffectsSession attachEffects(Context context, AudioRecord recorder, boolean forActiveDialog) {
        if (recorder == null) return new EffectsSession(0, false, false);
        boolean wantAec = forActiveDialog && isAecEnabled(context);
        boolean wantNs = isNsEnabled(context);
        return new EffectsSession(recorder.getAudioSessionId(), wantAec, wantNs);
    }

    /** Returns true when another app or telephony call holds the microphone/voice call mode. */
    static boolean othersNeedMic(Context context) {
        AudioManager am = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        if (am == null) return false;
        int mode = am.getMode();
        if (mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_RINGTONE) {
            return true;
        }
        if (Build.VERSION.SDK_INT >= 29) {
            try {
                List<AudioRecordingConfiguration> active = am.getActiveRecordingConfigurations();
                for (AudioRecordingConfiguration cfg : active) {
                    int src = cfg.getClientAudioSource();
                    if (src == MediaRecorder.AudioSource.VOICE_COMMUNICATION && mode == AudioManager.MODE_IN_COMMUNICATION) {
                        return true;
                    }
                }
            } catch (RuntimeException ignored) {}
        }
        return false;
    }

    /** Activates Bluetooth communication/SCO route if a BT headset is connected and BT SCO is enabled. */
    static boolean acquireBluetoothRoute(Context context) {
        if (!isBtScoEnabled(context)) return false;
        if (Build.VERSION.SDK_INT >= 31 && context.checkSelfPermission(android.Manifest.permission.BLUETOOTH_CONNECT)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) return false;
        AudioManager am = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        if (am == null) return false;
        if (Build.VERSION.SDK_INT >= 31) {
            try {
                AudioDeviceInfo bt = findBluetoothDevice(am.getAvailableCommunicationDevices());
                if (bt != null) {
                    boolean ok = am.setCommunicationDevice(bt);
                    Log.i(TAG, "setCommunicationDevice bt=" + deviceTypeName(bt.getType()) + " ok=" + ok);
                    return ok;
                }
            } catch (RuntimeException error) {
                Log.w(TAG, "setCommunicationDevice failed", error);
            }
            return false;
        }
        AudioDeviceInfo[] inputs = am.getDevices(AudioManager.GET_DEVICES_INPUTS);
        for (AudioDeviceInfo dev : inputs) {
            int type = dev.getType();
            if (type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO && am.isBluetoothScoAvailableOffCall()) {
                try {
                    am.startBluetoothSco();
                    am.setBluetoothScoOn(true);
                    Log.i(TAG, "startBluetoothSco");
                    return true;
                } catch (RuntimeException error) {
                    Log.w(TAG, "startBluetoothSco failed", error);
                }
            }
        }
        return false;
    }

    static void releaseBluetoothRoute(Context context) {
        AudioManager am = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        if (am == null) return;
        if (Build.VERSION.SDK_INT >= 31) {
            try { am.clearCommunicationDevice(); } catch (RuntimeException ignored) {}
        } else {
            try {
                if (am.isBluetoothScoOn()) am.setBluetoothScoOn(false);
                am.stopBluetoothSco();
            } catch (RuntimeException ignored) {}
        }
    }

    static String describeMicRoute(AudioRecord recorder) {
        if (recorder == null) return "NONE";
        String source = switch (recorder.getAudioSource()) {
            case MediaRecorder.AudioSource.VOICE_RECOGNITION -> "VOICE_RECOGNITION";
            case MediaRecorder.AudioSource.VOICE_COMMUNICATION -> "VOICE_COMMUNICATION";
            case MediaRecorder.AudioSource.MIC -> "MIC";
            default -> "SRC_" + recorder.getAudioSource();
        };
        String device = "DEFAULT";
        try {
            AudioDeviceInfo routed = recorder.getRoutedDevice();
            if (routed != null) device = deviceTypeName(routed.getType());
        } catch (RuntimeException ignored) {}
        return source + "/" + device;
    }

    static String routeSummary(Context context) {
        AudioManager am = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        String bt = "нет";
        if (am != null) {
            for (AudioDeviceInfo dev : am.getDevices(AudioManager.GET_DEVICES_INPUTS)) {
                int t = dev.getType();
                if (t == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || t == AudioDeviceInfo.TYPE_BLE_HEADSET) {
                    bt = deviceTypeName(t) + " (" + dev.getProductName() + ")";
                    break;
                }
            }
        }
        return "AEC: " + (AcousticEchoCanceler.isAvailable() ? (isAecEnabled(context) ? "вкл" : "откл") : "нет в системе")
                + " · NS: " + (NoiseSuppressor.isAvailable() ? (isNsEnabled(context) ? "вкл" : "откл") : "нет в системе")
                + " · BT-гарнитура: " + bt;
    }

    private static AudioDeviceInfo findBluetoothDevice(List<AudioDeviceInfo> devices) {
        for (AudioDeviceInfo dev : devices) {
            int t = dev.getType();
            if (t == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || t == AudioDeviceInfo.TYPE_BLE_HEADSET) return dev;
        }
        return null;
    }

    static String deviceTypeName(int type) {
        return switch (type) {
            case AudioDeviceInfo.TYPE_BUILTIN_MIC -> "BUILTIN_MIC";
            case AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "BLUETOOTH_SCO";
            case AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> "BLUETOOTH_A2DP";
            case AudioDeviceInfo.TYPE_WIRED_HEADSET -> "WIRED_HEADSET";
            case AudioDeviceInfo.TYPE_USB_HEADSET -> "USB_HEADSET";
            case AudioDeviceInfo.TYPE_USB_DEVICE -> "USB_DEVICE";
            case AudioDeviceInfo.TYPE_BLE_HEADSET -> "BLE_HEADSET";
            default -> "TYPE_" + type;
        };
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private AudioRouteManager() {}
}
