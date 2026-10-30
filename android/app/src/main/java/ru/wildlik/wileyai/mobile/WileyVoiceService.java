package ru.wildlik.wileyai.mobile;

import android.content.*;
import android.os.Bundle;
import android.service.voice.VoiceInteractionService;

/** System-selected assistant entry point. Heavy audio/LLM work lives in the explicit foreground service. */
public final class WileyVoiceService extends VoiceInteractionService {
    private static WileyVoiceService current;
    static boolean ready() { return current != null; }
    static boolean selected(Context context) { return isActiveService(context, new ComponentName(context, WileyVoiceService.class)); }
    static boolean invoke() { return invoke(false); }
    static boolean invoke(boolean conversation) { if (current == null) return false; try { Bundle args=new Bundle();args.putBoolean("conversation",conversation);current.showSession(args, 0); return true; } catch (IllegalStateException disconnected) { current = null; return false; } }
    @Override public void onShowSessionFailed(Bundle args) { HandsFreeService.sessionFailed(); }
    @Override public void onLaunchVoiceAssistFromKeyguard() { showSession(new Bundle(), 0); }
    @Override public void onReady() { super.onReady(); setDisabledShowContext(android.service.voice.VoiceInteractionSession.SHOW_WITH_ASSIST | android.service.voice.VoiceInteractionSession.SHOW_WITH_SCREENSHOT); current = this; if (getSharedPreferences("wiley-mobile", MODE_PRIVATE).getBoolean("handsfree_enabled", false)) { try { startForegroundService(new Intent(this, HandsFreeService.class).setAction(HandsFreeService.ENABLE)); } catch (RuntimeException denied) { getSharedPreferences("wiley-mobile", MODE_PRIVATE).edit().putBoolean("handsfree_enabled", false).apply(); } } }
    @Override public void onShutdown() { if (current == this) current = null; getSharedPreferences("wiley-mobile", MODE_PRIVATE).edit().putBoolean("handsfree_enabled", false).apply(); stopService(new Intent(this, HandsFreeService.class)); super.onShutdown(); }
    @Override public void onDestroy() { if (current == this) current = null; super.onDestroy(); }
}
