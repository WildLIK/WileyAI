package ru.wildlik.wileyai.mobile;

import android.content.*;
import android.media.*;
import android.media.audiofx.*;
import android.media.session.*;
import android.os.Build;
import org.json.*;

import static ru.wildlik.wileyai.mobile.AcousticStore.*;

/** Observe existing system state. No effect is created, enabled or rerouted. */
final class AcousticRoute {
    static void fill(Context context, AudioRecord mic, JSONObject row) {
        AudioManager manager = context.getSystemService(AudioManager.class);
        set(row, "input_type", "unknown");
        set(row, "output_route", "unknown");
        set(row, "media_app", "unknown");
        set(row, "effects_observed", "unknown");
        set(row, "wiley_tts", HandsFreeService.acousticSpeaking());
        set(row, "noise_suppressor_available", NoiseSuppressor.isAvailable());
        set(row, "aec_available", AcousticEchoCanceler.isAvailable());
        set(row, "agc_available", AutomaticGainControl.isAvailable());
        try {
            AudioDeviceInfo device = mic.getRoutedDevice();
            if (device != null && device.isSource()) {
                set(row, "input_type", device.getType());
                set(row, "input_id", device.getId());
            }
            set(row, "audio_session", mic.getAudioSessionId());
            set(row, "source", mic.getAudioSource());
            set(row, "rate", mic.getSampleRate());
            set(row, "channels", mic.getChannelCount());
            set(row, "encoding", mic.getAudioFormat());
            set(row, "buffer_frames", mic.getBufferSizeInFrames());
            if (Build.VERSION.SDK_INT >= 29) {
                AudioRecordingConfiguration config = mic.getActiveRecordingConfiguration();
                if (config != null) {
                    JSONArray effects = new JSONArray();
                    for (AudioEffect.Descriptor item : config.getEffects()) effects.put(item.type.toString());
                    set(row, "effects_observed", effects);
                    JSONArray clientEffects = new JSONArray();
                    for (AudioEffect.Descriptor item : config.getClientEffects()) clientEffects.put(item.type.toString());
                    set(row, "client_effects_observed", clientEffects);
                    set(row, "silenced", config.isClientSilenced());
                }
            }
        } catch (RuntimeException unavailable) { set(row, "input_observation_error", "not_available"); }
        if (manager == null) return;
        try {
            set(row, "media_active", manager.isMusicActive());
            set(row, "media_volume", manager.getStreamVolume(AudioManager.STREAM_MUSIC));
            set(row, "media_volume_max", manager.getStreamMaxVolume(AudioManager.STREAM_MUSIC));
            if (Build.VERSION.SDK_INT >= 31) {
                JSONArray outputs = new JSONArray();
                for (AudioPlaybackConfiguration playback : manager.getActivePlaybackConfigurations()) {
                    if (playback.getAudioAttributes().getUsage() != AudioAttributes.USAGE_MEDIA) continue;
                    AudioDeviceInfo device = playback.getAudioDeviceInfo();
                    if (device != null && device.isSink()) outputs.put(fields("type", device.getType(), "id", device.getId()));
                }
                if (outputs.length() > 0) set(row, "output_route", outputs);
            }
        } catch (RuntimeException unavailable) { set(row, "media_observation_error", "not_available"); }
        try {
            MediaSessionManager sessions = context.getSystemService(MediaSessionManager.class);
            if (sessions != null) {
                JSONArray apps = new JSONArray();
                for (MediaController controller : sessions.getActiveSessions(new ComponentName(context, MediaAccessService.class))) {
                    PlaybackState state = controller.getPlaybackState();
                    if (state != null && state.getState() == PlaybackState.STATE_PLAYING) apps.put(controller.getPackageName());
                    if (apps.length() == 8) break;
                }
                if (apps.length() > 0) set(row, "media_app", apps);
            }
        } catch (SecurityException unavailable) { /* Existing media access only. */ }
    }
    private AcousticRoute() {}
}
