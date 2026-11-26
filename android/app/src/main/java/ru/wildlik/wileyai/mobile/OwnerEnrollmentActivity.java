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
import java.util.Locale;

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
    private TextView profileStatus, captureStatus;
    private Button recordBtn, saveBtn, testBtn, clearBtn;
    private volatile boolean busy;

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        ui = new MobileUi(this, new SettingsRepository(this).theme());
        LinearLayout root = ui.vertical();
        root.setPadding(ui.dp(16), ui.dp(14), ui.dp(16), ui.dp(18));
        root.setBackgroundColor(ui.theme.base);

        root.addView(ui.text("Регистрация голоса владельца", 22, ui.theme.text));
        root.addView(ui.text(
                "Запись начинается только по нажатию кнопки и хранится локально в виде эмбеддинга CAM++. "
                        + "Чужие голоса никогда не дообучаются автоматически.",
                14, ui.theme.secondary));

        profileStatus = ui.text("", 15, ui.theme.accentText);
        profileStatus.setPadding(0, ui.dp(8), 0, ui.dp(6));
        root.addView(profileStatus);

        captureStatus = ui.text("", 15, ui.theme.text);
        captureStatus.setPadding(0, ui.dp(4), 0, ui.dp(10));
        root.addView(captureStatus);

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
        refreshUi();
    }

    private void refreshUi() {
        boolean enrolled = OwnerSpeakerFilter.hasEnrolledProfile(this);
        profileStatus.setText(enrolled
                ? "Профиль владельца: зарегистрирован (CAM++ 3D-Speaker)"
                : "Профиль владельца: не зарегистрирован");
        int n = clips.size();
        String next = PROMPTS[n % PROMPTS.length];
        captureStatus.setText("Записано фраз: " + n + " / 3–5\nСледующая фраза: «" + next + "»");
        recordBtn.setEnabled(!busy && n < 5);
        recordBtn.setText(busy ? "Идёт запись…" : n >= 5 ? "Записано максимум 5 фраз" : "Записать фразу («" + next + "»)");
        saveBtn.setEnabled(!busy && n >= 3);
        testBtn.setEnabled(!busy && enrolled);
        clearBtn.setEnabled(!busy && (enrolled || n > 0));
    }

    private void recordNextPhrase() {
        if (busy) return;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            captureStatus.setText("Нет разрешения на микрофон.");
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
                if (finalClip != null) {
                    clips.add(finalClip);
                } else if (finalErr != null) {
                    captureStatus.setText("Ошибка: " + finalErr);
                }
                refreshUi();
            });
        }, "OwnerEnrollCapture").start());
    }

    private void saveEnrollment() {
        if (busy || clips.size() < 3) return;
        busy = true;
        refreshUi();
        List<short[]> copy = new ArrayList<>(clips);
        new Thread(() -> {
            String msg;
            try {
                Path camModel = WakeModelAssets.ensureCamPlus(this);
                try (OwnerSpeakerFilter filter = OwnerSpeakerFilter.open(camModel, 1)) {
                    int used = filter.enroll(this, copy);
                    msg = "Профиль владельца сохранён (" + used + " фраз).";
                }
            } catch (Exception e) {
                msg = "Ошибка регистрации: " + e.getMessage();
            }
            String finalMsg = msg;
            main.post(() -> {
                busy = false;
                clips.clear();
                refreshUi();
                profileStatus.setText(finalMsg);
            });
        }, "OwnerEnrollSave").start();
    }

    private void testLiveSimilarity() {
        if (busy || !OwnerSpeakerFilter.hasEnrolledProfile(this)) return;
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
                    resultText = String.format(Locale.ROOT,
                            "%s · сходство=%.3f (порог %.2f, %.1f ms)",
                            r.accepted() ? "Владелец подтверждён" : "Отклонён как чужой",
                            r.similarity(), r.threshold(), r.elapsedUs() / 1000.0);
                }
            } catch (Exception e) {
                resultText = "Ошибка проверки: " + e.getMessage();
            } finally {
                HandsFreeService.resumeExternal();
            }
            String finalMsg = resultText;
            main.post(() -> {
                busy = false;
                refreshUi();
                profileStatus.setText(finalMsg);
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
