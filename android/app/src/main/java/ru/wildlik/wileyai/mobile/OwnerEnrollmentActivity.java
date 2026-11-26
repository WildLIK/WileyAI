package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Explicit local-only owner voice enrollment for CAM++ 3D-Speaker.
 * No background capture and strictly zero automatic learning on strangers.
 */
public final class OwnerEnrollmentActivity extends Activity {
    private static final int SAMPLE_RATE = 16000;
    private static final int RECORD_SAMPLES = SAMPLE_RATE * 5 / 2; // 2.5 s per phrase
    private static final String[] PROMPTS = {
            "Вайли",
            "Окей, Вайли",
            "Вайли, сколько времени?",
            "Вайли, включи музыку",
            "Вайли, поставь на паузу"
    };

    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<short[]> clips = new ArrayList<>();
    private MobileUi ui;
    private RuntimeAccess access;
    private TextView profileStatus, captureStatus;
    private Button recordBtn, saveBtn, testBtn, clearBtn, repairBtn;
    private volatile boolean busy;
    private boolean modelReady;
    private String message = "";

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        String theme = new SettingsRepository(this).theme();
        ui = new MobileUi(this, "system".equals(theme) ? "aurora" : theme);
        access = new RuntimeAccess(this);
        LinearLayout root = ui.vertical();
        root.setPadding(ui.dp(16), ui.dp(14), ui.dp(16), ui.dp(18));
        root.setBackgroundColor(ui.theme.base);

        ui.card(root, "Мой голос", "Запишите 3–5 фраз. WileyAI сохранит на телефоне голосовой профиль. Сами записи нужны только во время настройки.");

        profileStatus = ui.text("", 15, ui.theme.accentText);
        profileStatus.setPadding(0, ui.dp(8), 0, ui.dp(6));
        root.addView(profileStatus);

        captureStatus = ui.text("", 15, ui.theme.text);
        captureStatus.setPadding(0, ui.dp(4), 0, ui.dp(10));
        root.addView(captureStatus);
        repairBtn = ui.button("Проверить или восстановить компонент", this::prepareModel);
        root.addView(repairBtn);

        recordBtn = ui.button("", this::recordNextPhrase);
        root.addView(recordBtn);

        saveBtn = ui.button("Сохранить профиль владельца", this::saveEnrollment);
        root.addView(saveBtn);

        testBtn = ui.button("Проверить мой голос (2.5 с)", this::testLiveSimilarity);
        root.addView(testBtn);

        clearBtn = ui.button("Удалить профиль владельца", this::confirmClear);
        root.addView(clearBtn);

        root.addView(ui.button("Назад", this::finish));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.addView(root);
        setContentView(scroll);
        prepareModel();
    }

    @Override protected void onResume() { super.onResume(); if (recordBtn != null) refreshUi(); }

    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        access.returned(code, permissions, results, ui, this::refreshUi);
    }

    private void prepareModel() {
        if (busy) return;
        busy = true;
        message = "Проверяю компонент голосового профиля…";
        refreshUi();
        new Thread(() -> {
            boolean ready = false;
            try (OwnerSpeakerFilter ignored = OwnerSpeakerFilter.open(WakeModelAssets.ensureCamPlus(this), 1)) {
                ready = true;
            } catch (Exception | LinkageError error) {
                android.util.Log.w("WileyOwner", "speaker_component_unavailable");
            }
            boolean available = ready;
            main.post(() -> {
                if (isDestroyed()) return;
                busy = false;
                modelReady = available;
                message = available ? "" : "Компонент голосового профиля недоступен. Попробуйте восстановить его или вернитесь к голосовому вызову и выберите Vosk.";
                refreshUi();
            });
        }, "OwnerComponentCheck").start();
    }

    private void refreshUi() {
        boolean enrolled = OwnerSpeakerFilter.hasEnrolledProfile(this);
        profileStatus.setText(!message.isEmpty() ? message : enrolled
                ? "Профиль голоса сохранён" : "Профиль голоса ещё не создан");
        int n = clips.size();
        String next = PROMPTS[n % PROMPTS.length];
        captureStatus.setText("Записано фраз: " + n + " / 3–5\nСледующая фраза: «" + next + "»");
        repairBtn.setVisibility(!busy && !modelReady ? android.view.View.VISIBLE : android.view.View.GONE);
        recordBtn.setEnabled(!busy && modelReady && n < 5);
        recordBtn.setText(busy ? "Идёт запись…" : n >= 5 ? "Записано максимум 5 фраз" : "Записать фразу («" + next + "»)");
        saveBtn.setEnabled(!busy && modelReady && n >= 3);
        testBtn.setEnabled(!busy && modelReady && enrolled);
        clearBtn.setEnabled(!busy && (enrolled || n > 0));
    }

    private void recordNextPhrase() {
        if (busy || !modelReady) return;
        if (!access.granted(RuntimeAccess.Item.MIC)) {
            access.request(RuntimeAccess.Item.MIC, ui, this::recordNextPhrase);
            return;
        }
        busy = true;
        refreshUi();
        HandsFreeService.pauseExternal(() -> new Thread(() -> {
            short[] captured = null;
            String err = null;
            try {
                captured = capturePcm(RECORD_SAMPLES);
            } catch (Exception e) {
                err = e.getMessage() != null ? e.getMessage() : "Ошибка записи микрофона";
            } finally {
                HandsFreeService.resumeExternal();
            }
            short[] finalClip = captured;
            String finalErr = err;
            main.post(() -> {
                busy = false;
                if (isDestroyed()) return;
                if (finalClip != null) {
                    clips.add(finalClip);
                    message = "";
                } else if (finalErr != null) {
                    message = "Не удалось записать фразу. Проверьте микрофон и повторите попытку.";
                }
                refreshUi();
            });
        }, "OwnerEnrollCapture").start());
    }

    private void saveEnrollment() {
        if (busy || !modelReady || clips.size() < 3) return;
        busy = true;
        refreshUi();
        List<short[]> copy = new ArrayList<>(clips);
        new Thread(() -> {
            String msg;
            boolean saved = false;
            try {
                Path camModel = WakeModelAssets.ensureCamPlus(this);
                try (OwnerSpeakerFilter filter = OwnerSpeakerFilter.open(camModel, 1)) {
                    int used = filter.enroll(this, copy);
                    msg = "Профиль владельца сохранён (" + used + " фраз).";
                    saved = true;
                }
            } catch (Exception | LinkageError e) {
                msg = "Не удалось сохранить профиль. Проверьте, что фразы записались разборчиво, и повторите попытку.";
            }
            String finalMsg = msg;
            boolean committed = saved;
            main.post(() -> {
                if (isDestroyed()) return;
                busy = false;
                if (committed) clips.clear();
                message = finalMsg;
                refreshUi();
            });
        }, "OwnerEnrollSave").start();
    }

    private void testLiveSimilarity() {
        if (busy || !modelReady || !OwnerSpeakerFilter.hasEnrolledProfile(this)) return;
        if (!access.granted(RuntimeAccess.Item.MIC)) {
            access.request(RuntimeAccess.Item.MIC, ui, this::testLiveSimilarity);
            return;
        }
        busy = true;
        refreshUi();
        profileStatus.setText("Говорите сейчас (2.5 с)…");
        HandsFreeService.pauseExternal(() -> new Thread(() -> {
            String resultText;
            try {
                short[] pcm = capturePcm(RECORD_SAMPLES);
                Path camModel = WakeModelAssets.ensureCamPlus(this);
                try (OwnerSpeakerFilter filter = OwnerSpeakerFilter.open(camModel, 1)) {
                    float[] ref = OwnerSpeakerFilter.loadProfile(this);
                    float thr = OwnerSpeakerFilter.threshold(this);
                    OwnerSpeakerFilter.Result r = filter.verifyAgainstReference(ref, pcm, pcm.length, thr);
                    resultText = r.accepted() ? "Голос совпал с профилем." : "Голос не совпал с профилем. Попробуйте говорить в тихом месте.";
                }
            } catch (Exception | LinkageError e) {
                resultText = "Не удалось проверить голос. Повторите запись в тихом месте.";
            } finally {
                HandsFreeService.resumeExternal();
            }
            String finalMsg = resultText;
            main.post(() -> {
                if (isDestroyed()) return;
                busy = false;
                message = finalMsg;
                refreshUi();
            });
        }, "OwnerEnrollTest").start());
    }

    private void confirmClear() {
        ui.dialog().setTitle("Удалить профиль голоса?")
                .setMessage("Локальный профиль владельца CAM++ и незаписанные фразы будут удалены.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Удалить", (d, w) -> {
                    try { OwnerSpeakerFilter.clearEnrollment(this); } catch (Exception ignored) {}
                    clips.clear();
                    message = "";
                    refreshUi();
                }).show();
    }

    private short[] capturePcm(int targetSamples) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            throw new SecurityException("Нет разрешения на микрофон");
        }
        int minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord rec = new AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(8192, minBuf * 2));
        if (rec.getState() != AudioRecord.STATE_INITIALIZED) {
            rec.release();
            throw new IllegalStateException("Микрофон недоступен");
        }
        short[] out = new short[targetSamples];
        int pos = 0;
        try {
            rec.startRecording();
            while (pos < targetSamples && !isFinishing()) {
                int n = rec.read(out, pos, Math.min(2048, targetSamples - pos));
                if (n <= 0) break;
                pos += n;
            }
        } finally {
            try { rec.stop(); } catch (IllegalStateException ignored) {}
            rec.release();
        }
        if (pos < OwnerSpeakerFilter.MIN_SAMPLES) {
            throw new IllegalStateException("Слишком короткая запись");
        }
        return java.util.Arrays.copyOf(out, pos);
    }
}
