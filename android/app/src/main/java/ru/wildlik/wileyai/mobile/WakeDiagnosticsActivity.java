package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import java.nio.file.Path;
import java.util.List;
import java.util.Locale;

/**
 * Activation diagnostic journal & user feedback UI:
 * - Pre/post WAV playback, confidence, CAM++ similarity, mic source, TTS state, latencies, reason.
 * - Manual false-alarm marking & missed-command recording.
 * - Consent-gated ZIP export & delete all.
 */
public final class WakeDiagnosticsActivity extends Activity {
    private static final int SAMPLE_RATE = 16000;
    private static final int MISSED_SAMPLES = SAMPLE_RATE * 7 / 2; // 3.5 s

    private final Handler main = new Handler(Looper.getMainLooper());
    private MobileUi ui;
    private LinearLayout listBox;
    private TextView summaryText;
    private Button missedBtn;
    private MediaPlayer player;
    private volatile boolean recordingMissed;

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        ui = new MobileUi(this, new SettingsRepository(this).theme());
        LinearLayout root = ui.vertical();
        root.setPadding(ui.dp(16), ui.dp(14), ui.dp(16), ui.dp(18));
        root.setBackgroundColor(ui.theme.base);

        root.addView(ui.text("Журнал активаций и диагностика", 22, ui.theme.text));

        Switch enabled = new Switch(this);
        enabled.setText("Записывать журнал активаций (до/после WAV)");
        enabled.setTextColor(ui.theme.text);
        enabled.setMinHeight(ui.dp(52));
        enabled.setChecked(WakeActivationJournal.isEnabled(this));
        enabled.setOnCheckedChangeListener((b, on) -> WakeActivationJournal.setEnabled(this, on));
        ui.styleControl(enabled);
        root.addView(enabled);

        summaryText = ui.text("", 14, ui.theme.secondary);
        summaryText.setPadding(0, ui.dp(4), 0, ui.dp(8));
        root.addView(summaryText);

        root.addView(ui.button("Отметить последнее ложное срабатывание", () -> {
            String msg = WakeActivationJournal.markLastFalseAlarm(this);
            Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
            refreshList();
        }));

        missedBtn = ui.button("Записать пропущенную команду (3.5 с)", this::recordMissedCommand);
        root.addView(missedBtn);

        root.addView(ui.button("Экспортировать диагностику в ZIP", this::confirmExportZip));
        root.addView(ui.button("Удалить все записи журнала", this::confirmClearAll));

        listBox = ui.vertical();
        root.addView(listBox);
        root.addView(ui.button("Назад", this::finish));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.addView(root);
        setContentView(scroll);
        refreshList();
    }

    @Override protected void onDestroy() {
        stopPlayback();
        super.onDestroy();
    }

    private void refreshList() {
        List<WakeActivationJournal.Entry> entries = WakeActivationJournal.listEvents(this);
        summaryText.setText("Событий в журнале: " + entries.size() + " · " + AudioRouteManager.routeSummary(this));
        listBox.removeAllViews();
        if (entries.isEmpty()) {
            listBox.addView(ui.text("Записей пока нет.", 14, ui.theme.secondary));
            return;
        }
        int limit = Math.min(40, entries.size());
        for (int i = 0; i < limit; i++) {
            WakeActivationJournal.Entry e = entries.get(i);
            Button item = ui.button(e.summary(), () -> showEntryDetails(e));
            listBox.addView(item);
        }
    }

    private void showEntryDetails(WakeActivationJournal.Entry e) {
        StringBuilder sb = new StringBuilder();
        sb.append("Время UTC: ").append(e.timestampUtc()).append('\n');
        sb.append("Движок: ").append(e.engine()).append('\n');
        sb.append("Исход: ").append(e.outcome()).append(" (").append(e.reason()).append(")\n");
        sb.append("Confidence: ").append(Double.isNaN(e.confidence()) ? "—" : String.format(Locale.ROOT, "%.4f", e.confidence())).append('\n');
        sb.append("Speaker sim: ").append(Double.isNaN(e.speakerSimilarity()) ? "—" : String.format(Locale.ROOT, "%.4f (порог %.2f)", e.speakerSimilarity(), e.speakerThreshold())).append('\n');
        sb.append("Микрофон: ").append(e.micSource()).append('\n');
        sb.append("TTS активен: ").append(e.ttsSpeaking() ? "да" : "нет").append('\n');
        sb.append("Задержка wake / CAM++: ").append(e.wakeLatencyMs()).append(" ms / ").append(e.camLatencyMs()).append(" ms\n");
        if (!e.asrText().isEmpty()) sb.append("Распознано ASR: «").append(e.asrText()).append("»\n");
        if (!e.userLabel().isEmpty()) sb.append("Метка пользователя: ").append(e.userLabel()).append('\n');

        var dlg = ui.dialog().setTitle("Детали события").setMessage(sb.toString())
                .setNeutralButton("Ложное срабатывание", (d, w) -> {
                    WakeActivationJournal.markFalseAlarm(this, e.id());
                    refreshList();
                })
                .setNegativeButton("Закрыть", null);
        if (e.hasPreWav()) {
            dlg.setPositiveButton(e.hasPostWav() ? "Слушать до/после" : "Слушать до", (d, w) -> {
                Path dir = WakeActivationJournal.rootDir(this).resolve(e.id());
                playWav(dir.resolve("pre.wav"), e.hasPostWav() ? dir.resolve("post.wav") : null);
            });
        }
        dlg.show();
    }

    private void playWav(Path first, Path second) {
        stopPlayback();
        try {
            player = new MediaPlayer();
            player.setDataSource(first.toAbsolutePath().toString());
            player.setOnCompletionListener(mp -> {
                if (second != null) {
                    playWav(second, null);
                } else {
                    stopPlayback();
                }
            });
            player.prepare();
            player.start();
        } catch (Exception e) {
            Toast.makeText(this, "Не удалось воспроизвести аудиофрагмент", Toast.LENGTH_SHORT).show();
        }
    }

    private void stopPlayback() {
        if (player != null) {
            try { player.stop(); } catch (Exception ignored) {}
            try { player.release(); } catch (Exception ignored) {}
            player = null;
        }
    }

    private void recordMissedCommand() {
        if (recordingMissed) return;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(this, "Разрешите микрофон в настройках", Toast.LENGTH_SHORT).show();
            return;
        }
        recordingMissed = true;
        missedBtn.setEnabled(false);
        missedBtn.setText("Говорите пропущенную команду (3.5 с)…");
        HandsFreeService.pauseExternal(() -> new Thread(() -> {
            int minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            AudioRecord rec = new AudioRecord(
                    MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(8192, minBuf * 2));
            short[] pcm = new short[MISSED_SAMPLES];
            int pos = 0;
            try {
                if (rec.getState() == AudioRecord.STATE_INITIALIZED) {
                    rec.startRecording();
                    while (pos < MISSED_SAMPLES && !isFinishing()) {
                        int n = rec.read(pcm, pos, Math.min(2048, MISSED_SAMPLES - pos));
                        if (n <= 0) break;
                        pos += n;
                    }
                }
            } finally {
                try { rec.stop(); } catch (IllegalStateException ignored) {}
                rec.release();
                HandsFreeService.resumeExternal();
            }
            if (pos > 0) {
                WakeActivationJournal.recordMissedCommandAsync(this, pcm, pos, "user_missed_command");
            }
            main.postDelayed(() -> {
                recordingMissed = false;
                missedBtn.setEnabled(true);
                missedBtn.setText("Записать пропущенную команду (3.5 с)");
                refreshList();
                Toast.makeText(this, "Пропущенная команда сохранена в журнал", Toast.LENGTH_SHORT).show();
            }, 250);
        }, "MissedCommandCapture").start());
    }

    private void confirmExportZip() {
        List<WakeActivationJournal.Entry> entries = WakeActivationJournal.listEvents(this);
        if (entries.isEmpty()) {
            Toast.makeText(this, "Журнал пуст", Toast.LENGTH_SHORT).show();
            return;
        }
        ui.dialog().setTitle("Экспортировать диагностику в ZIP?")
                .setMessage("Архив содержит " + entries.size() + " событий, включая локальные аудиофрагменты (до/после срабатывания) и метаданные. Файл не отправляется автоматически без вашего выбора получателя.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Подготовить ZIP", (d, w) -> new Thread(() -> {
                    try {
                        Path zipPath = getCacheDir().toPath().resolve("wileyai-wake-journal.zip");
                        WakeActivationJournal.exportZip(this, zipPath);
                        Uri uri = new Uri.Builder()
                                .scheme("content")
                                .authority(getPackageName() + ".diagnostics")
                                .appendPath("wake-journal.zip")
                                .build();
                        Intent send = new Intent(Intent.ACTION_SEND)
                                .setType("application/zip")
                                .putExtra(Intent.EXTRA_STREAM, uri)
                                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        send.setClipData(ClipData.newRawUri("WileyAI Wake Journal", uri));
                        main.post(() -> startActivity(Intent.createChooser(send, "Поделиться журналом активаций (ZIP)")));
                    } catch (Exception e) {
                        main.post(() -> Toast.makeText(this, "Ошибка экспорта ZIP: " + e.getMessage(), Toast.LENGTH_SHORT).show());
                    }
                }, "WakeJournalZipExport").start())
                .show();
    }

    private void confirmClearAll() {
        ui.dialog().setTitle("Удалить все записи?")
                .setMessage("Все аудиофрагменты и метаданные журнала активаций будут удалены с телефона.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Удалить", (d, w) -> {
                    WakeActivationJournal.clearAll(this);
                    refreshList();
                    Toast.makeText(this, "Журнал активаций очищен", Toast.LENGTH_SHORT).show();
                }).show();
    }
}
