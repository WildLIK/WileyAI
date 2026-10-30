package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.content.*;
import android.os.*;
import android.speech.tts.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import org.json.JSONObject;

/** Explicit opt-in physical speaker-to-microphone check. No audio file or ambient transcript is retained. */
final class AssistantLoopbackProbe {
    private static void check(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void await(BooleanSupplier condition, long timeout, String reason) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + timeout;
        while (!condition.getAsBoolean() && SystemClock.elapsedRealtime() < deadline) Thread.sleep(80);
        check(condition.getAsBoolean(), reason + ": " + HandsFreeService.status());
    }
    static String run(Instrumentation runner, Context context) throws Exception {
        check(WileyVoiceService.selected(context), "Select WileyAI using Android Settings first");
        check(context.getSharedPreferences("wiley-mobile",0).getBoolean("handsfree_enabled",false), "Enable background microphone using WileyAI UI first");
        TextToSpeech[] producer = new TextToSpeech[1]; CountDownLatch ready = new CountDownLatch(1); AtomicReference<String> error = new AtomicReference<>();
        try {
            runner.runOnMainSync(() -> producer[0] = new TextToSpeech(context, code -> { if (code != TextToSpeech.SUCCESS) error.set("TTS failed"); ready.countDown(); }, "com.google.android.tts"));
            check(ready.await(20, TimeUnit.SECONDS) && error.get() == null, "Google TTS unavailable");
            Voice voice = null;
            for (Voice item : producer[0].getVoices()) if (item.getLocale().getLanguage().equals("ru") && !item.isNetworkConnectionRequired() && (item.getFeatures() == null || !item.getFeatures().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED))) { voice = item; break; }
            check(voice != null, "No installed Russian offline voice"); producer[0].setVoice(voice); producer[0].setSpeechRate(1);
            runner.runOnMainSync(() -> context.startForegroundService(new Intent(context, HandsFreeService.class).setAction(HandsFreeService.ENABLE)));
            await(() -> HandsFreeService.status().startsWith("Скажите"), 20000, "Keyword listener not ready");
            // The launcher is foreground; no app recording button or assistant invoke API is used.
            try (ParcelFileDescriptor shell = runner.getUiAutomation().executeShellCommand("input keyevent KEYCODE_HOME")) { Thread.sleep(500); }
            long began = SystemClock.elapsedRealtime();
            String selected = context.getSharedPreferences("wiley-mobile",0).getString("wake_phrase",WakePhrase.DEFAULT);
            runner.runOnMainSync(() -> check(producer[0].speak(WakePhrase.label(selected), TextToSpeech.QUEUE_FLUSH, null, "wake-probe") == TextToSpeech.SUCCESS, "Wake synthesis rejected"));
            await(() -> HandsFreeService.status().equals("Слушаю команду…"), 20000, "No command listening after wake phrase");
            runner.runOnMainSync(() -> check(producer[0].speak("Сколько сейчас времени", TextToSpeech.QUEUE_FLUSH, null, "command-probe") == TextToSpeech.SUCCESS, "Command synthesis rejected"));
            await(() -> HandsFreeService.status().equals("Отвечаю голосом…"), 20000, "No spoken answer to the command");
            await(() -> HandsFreeService.status().startsWith("Скажите"), 30000, "Keyword listener did not resume after speech");
            return new JSONObject().put("source", "phone speaker Google TTS").put("microphone", true).put("main_activity_background", true).put("wake_phrase", true).put("command", "time").put("spoken_answer_completed", true).put("listener_resumed", true).put("elapsed_ms", SystemClock.elapsedRealtime()-began).toString();
        } finally { if (producer[0] != null) runner.runOnMainSync(producer[0]::shutdown); }
    }
    private AssistantLoopbackProbe() {}
}
