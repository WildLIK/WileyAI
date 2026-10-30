package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.SharedPreferences;
import android.view.View;
import android.widget.*;

/** Recognition has its own page; synthesis and phone actions live elsewhere. */
final class SpeechPanel {
    private final Activity activity;
    private final MobileUi ui;
    private final SpeechModelManager models;
    private final java.util.function.BooleanSupplier speech;
    private final SharedPreferences preferences;
    private final Runnable importZip;
    private TextView state;
    private ProgressBar progress;
    private Button download, pause, remove, discard;
    SpeechPanel(Activity activity, MobileUi ui, SpeechModelManager models, java.util.function.BooleanSupplier speech, SharedPreferences preferences, Runnable importZip) {
        this.activity = activity; this.ui = ui; this.models = models; this.speech = speech; this.preferences = preferences; this.importZip = importZip;
    }
    private boolean canChange() {
        if (HandsFreeService.running()) { ui.dialog().setMessage("Сначала остановите голосовую активацию в разделе «Голосовой помощник» или в уведомлении.").setPositiveButton("Понятно", null).show(); return false; }
        if (speech.getAsBoolean()) { ui.dialog().setMessage("Сначала завершите запись").setPositiveButton("Понятно", null).show(); return false; } return true;
    }
    void render(LinearLayout parent) {
        Button engine = ui.button("Распознавание: " + engineName(), () -> {});
        engine.setOnClickListener(v -> ui.dialog().setTitle("Как распознавать речь?").setItems(new String[]{"Vosk · автономно, установленный комплект", "Android · системная служба, возможен интернет", "Android · только на устройстве"}, (d,which) -> {
            Runnable save = () -> { preferences.edit().putInt("asr_engine", which).apply(); engine.setText("Распознавание: " + engineName()); };
            if (which == 1) ui.dialog().setTitle("Системное распознавание").setMessage("Звук получит выбранная в Android служба распознавания. Она может отправлять его на свои серверы и использовать интернет. WileyAI не управляет политикой этой службы. Использовать её для следующих нажатий микрофона?").setNegativeButton("Отмена", null).setPositiveButton("Использовать", (confirm,w) -> save.run()).show();
            else if (which == 2 && (android.os.Build.VERSION.SDK_INT < 31 || !android.speech.SpeechRecognizer.isOnDeviceRecognitionAvailable(activity))) ui.dialog().setMessage("Системное распознавание на устройстве недоступно. Vosk продолжит работать автономно.").setPositiveButton("Понятно", null).show();
            else save.run();
        }).setNegativeButton("Отмена", null).show()); parent.addView(engine);
        TextView help = ui.text("Понимает русскую речь на телефоне. После установки интернет и ПК не нужны.", 16, ui.theme.secondary); parent.addView(help);
        state = ui.text(models.detail(), 15, ui.theme.accentText); state.setPadding(0, ui.dp(16), 0, ui.dp(8)); parent.addView(state);
        progress = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal); progress.setMax(100); parent.addView(progress);
        download = ui.button("Скачать · 44,1 МиБ", this::confirmDownload); parent.addView(download);
        pause = ui.button("Приостановить загрузку", models::pause); parent.addView(pause);
        Switch wifi = new Switch(activity); wifi.setText("Скачивать только по Wi-Fi"); wifi.setTextColor(ui.theme.text); wifi.setMinHeight(ui.dp(56)); wifi.setChecked(preferences.getBoolean("speech_wifi_only", true));
        wifi.setOnCheckedChangeListener((button, checked) -> preferences.edit().putBoolean("speech_wifi_only", checked).apply()); parent.addView(wifi);
        LinearLayout advanced = ui.disclosure(parent, "Управление установкой и сведения");
        advanced.addView(ui.button("Импортировать ZIP с телефона", () -> { if (canChange() && !models.busy()) importZip.run(); }));
        discard = ui.button("Сбросить незавершённую загрузку", models::discardPartial); advanced.addView(discard);
        remove = ui.button("Удалить распознавание", () -> {
            if (canChange() && !models.busy()) ui.dialog().setTitle("Удалить распознавание?").setMessage("Голосовые команды потребуют повторной установки. Чаты сохранятся.").setNegativeButton("Отмена", null).setPositiveButton("Удалить", (d, w) -> models.remove()).show();
        }); advanced.addView(remove);
        advanced.addView(ui.button("Последняя попытка загрузки", () -> ui.dialog().setTitle("Диагностика загрузки").setMessage(models.diagnostic()).setPositiveButton("Закрыть", null).show()));
        ui.card(advanced, "Русский комплект Vosk", RussianSpeechModel.ID + "\nАрхив: 44,1 МиБ. Для безопасной установки нужно 400 МиБ свободного места. Лицензия: Apache-2.0. Сначала проверяются файл и загрузка движком; качество речи проверяется при использовании.");
        advanced.addView(ui.button("Источники и контрольные суммы", () -> ui.dialog().setTitle("Файл модели").setMessage("Основной источник: alphacephei.com\nРезерв: Hugging Face, закреплённая ревизия. В обоих случаях проверяется тот же архив.\n\nSHA-256: " + RussianSpeechModel.SPEC.sha256() + "\nMD5: " + RussianSpeechModel.SPEC.md5()).setPositiveButton("Закрыть", null).show())); refresh();
    }
    private String engineName() { int selected = preferences.getInt("asr_engine", 0); return selected == 1 ? "Android · возможна сеть" : selected == 2 ? "Android · на устройстве" : "Vosk · без интернета"; }
    void refresh() {
        if (state == null) return;
        state.setText(models.active() != null && !models.busy() ? "Русское распознавание установлено" : models.detail());
        progress.setVisibility(models.busy() ? View.VISIBLE : View.GONE); progress.setIndeterminate(models.percent() < 0); if (models.percent() >= 0) progress.setProgress(models.percent());
        download.setEnabled(!models.busy()); download.setText(models.busy() ? "Загрузка и установка…" : models.active() != null ? "Переустановить комплект" : models.partialBytes() > 0 ? "Продолжить загрузку · 44,1 МиБ" : "Скачать · 44,1 МиБ");
        pause.setVisibility(models.busy() ? View.VISIBLE : View.GONE); remove.setEnabled(!models.busy() && models.removable()); discard.setEnabled(!models.busy() && models.partialBytes() > 0);
    }
    private void confirmDownload() {
        if (!canChange()) return;
        ui.dialog().setTitle("Скачать русское распознавание?").setMessage("44,1 МиБ. Нужно 400 МиБ свободного места для установки.\n\nОсновной сервер Vosk, при сбое — проверенная копия на Hugging Face. " + (preferences.getBoolean("speech_wifi_only", true) ? "Только Wi-Fi." : "Разрешена любая сеть."))
            .setNegativeButton("Отмена", null).setPositiveButton("Скачать", (d, w) -> models.download(preferences.getBoolean("speech_wifi_only", true))).show();
    }
}
