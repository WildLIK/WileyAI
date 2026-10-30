package ru.wildlik.wileyai.mobile;

import android.content.*;
import android.os.*;
import android.speech.*;
import java.util.ArrayList;

/** Explicitly selected Android recognizer; network use is disclosed before the user enables it. */
final class SystemSpeechEngine {
    private final Context context; private SpeechRecognizer recognizer; private boolean busy;
    private final Handler timer = new Handler(Looper.getMainLooper()); private OfflineSpeechEngine.Listener active;
    SystemSpeechEngine(Context context) { this.context = context; }
    boolean busy() { return busy; }
    void start(boolean onDevice, OfflineSpeechEngine.Listener listener) {
        if (busy) return;
        if (!SpeechRecognizer.isRecognitionAvailable(context) || (onDevice && (Build.VERSION.SDK_INT < 31 || !SpeechRecognizer.isOnDeviceRecognitionAvailable(context)))) { listener.error("Этот системный распознаватель недоступен. Выберите Vosk или установите службу распознавания Android."); listener.finished(); return; }
        try {
            if (onDevice && Build.VERSION.SDK_INT >= 31) recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(context);
            else {
                android.content.ComponentName external = null;
                String selected = android.provider.Settings.Secure.getString(context.getContentResolver(), "voice_recognition_service");
                android.content.ComponentName configured = selected == null ? null : android.content.ComponentName.unflattenFromString(selected);
                // The optional system mode must not loop back to WileyAI's own Vosk service.
                if (configured != null && configured.getPackageName().equals(context.getPackageName())) {
                    for (android.content.pm.ResolveInfo match : context.getPackageManager().queryIntentServices(new Intent(RecognitionService.SERVICE_INTERFACE), 0)) {
                        android.content.pm.ServiceInfo info = match.serviceInfo;
                        if (info != null && info.enabled && info.exported && !info.packageName.equals(context.getPackageName()) && (info.applicationInfo.flags & android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0 && "android.permission.BIND_SPEECH_RECOGNITION_SERVICE".equals(info.permission)) {
                            external = new android.content.ComponentName(info.packageName, info.name);
                            if (info.packageName.equals("com.google.android.googlequicksearchbox")) break;
                        }
                    }
                    if (external == null) throw new IllegalStateException("No external system recognizer");
                }
                recognizer = external == null ? SpeechRecognizer.createSpeechRecognizer(context) : SpeechRecognizer.createSpeechRecognizer(context, external);
            }
            busy = true; active = listener;
            recognizer.setRecognitionListener(new RecognitionListener() {
                public void onReadyForSpeech(Bundle params) { listener.state(onDevice ? "Слушаю · Android на устройстве" : "Слушаю · системная служба Android, возможна сеть"); }
                public void onBeginningOfSpeech() {} public void onRmsChanged(float rms) {} public void onBufferReceived(byte[] buffer) {} public void onEndOfSpeech() {} public void onEvent(int type, Bundle params) {}
                public void onPartialResults(Bundle results) { ArrayList<String> text = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION); if (busy && text != null && !text.isEmpty()) listener.partial(text.get(0)); }
                public void onResults(Bundle results) { if (!busy) return; busy = false; ArrayList<String> text = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION); release(); listener.result(text == null || text.isEmpty() ? "" : text.get(0)); listener.finished(); }
                public void onError(int error) {
                    if (!busy) return; busy = false; release();
                    listener.error(error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT ? "Речь не распознана. Повторите фразу." : error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ? "Разрешите микрофон для распознавания" : error == SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED || error == SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE ? "Русский язык не установлен в системном распознавателе. Выберите Vosk или загрузите русский язык в настройках Android." : "Системное распознавание не ответило (код " + error + "). Проверьте сеть или выберите Vosk."); listener.finished();
                }
            });
            Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM).putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU").putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true).putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
            recognizer.startListening(intent);
            timer.postDelayed(() -> { if (busy) finish(); }, 15000);
        } catch (RuntimeException error) { busy = false; release(); listener.error("Не удалось запустить системное распознавание. Выберите Vosk."); listener.finished(); }
    }
    void finish() { if (recognizer != null && busy) { recognizer.stopListening(); timer.postDelayed(() -> { if (busy) { OfflineSpeechEngine.Listener listener = active; cancel(); if (listener != null) listener.error("Системное распознавание остановлено по тайм-ауту"); } }, 3000); } }
    void cancel() { boolean wasBusy = busy; busy = false; OfflineSpeechEngine.Listener listener = active; if (recognizer != null) recognizer.cancel(); release(); if (wasBusy && listener != null) listener.finished(); }
    private void release() { timer.removeCallbacksAndMessages(null); active = null; if (recognizer != null) { recognizer.destroy(); recognizer = null; } }
    void close() { cancel(); }
}
