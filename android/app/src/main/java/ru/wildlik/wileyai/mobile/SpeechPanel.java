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
    private final GigaAmModelManager gigaAm;
    private final java.util.function.BooleanSupplier speech;
    private final SharedPreferences preferences;
    private final Runnable importZip, gigaAmImport;
    private TextView state, gigaAmState, gigaAmRuntime;
    private ProgressBar progress, gigaAmProgress;
    private Button download, pause, remove, discard, gigaAmDownload, gigaAmPause, gigaAmRemove, gigaAmProbe, gigaAmUnload;
    SpeechPanel(Activity activity, MobileUi ui, SpeechModelManager models, GigaAmModelManager gigaAm, java.util.function.BooleanSupplier speech, SharedPreferences preferences, Runnable importZip, Runnable gigaAmImport) {
        this.activity = activity; this.ui = ui; this.models = models; this.gigaAm = gigaAm; this.speech = speech; this.preferences = preferences;
        this.importZip = importZip; this.gigaAmImport = gigaAmImport;
    }
    private boolean canChange() {
        if (HandsFreeService.running()) {
            SetupAction.show(ui,"Остановить фоновый вызов?", "Для изменения речевой модели сначала остановите прослушивание. Затем повторите действие.",
                    "Остановить", () -> HandsFreeService.stop(activity), null, null);
            return false;
        }
        if (speech.getAsBoolean()) { ui.dialog().setMessage("Сначала завершите запись").setPositiveButton("Понятно", null).show(); return false; } return true;
    }
    void render(LinearLayout parent) {
        Button engine = ui.button("Распознавание: " + engineName(), () -> {});
        engine.setOnClickListener(v -> ui.dialog().setTitle("Как распознавать речь?").setItems(new String[]{"Vosk · автономно, установленный комплект", "Android · системная служба, возможен интернет", "Android · только на устройстве", "GigaAM v3 · экспериментально, офлайн"}, (d,which) -> {
            Runnable save = () -> { preferences.edit().putInt("asr_engine", which).apply(); engine.setText("Распознавание: " + engineName()); };
            if (which == 1) ui.dialog().setTitle("Системное распознавание").setMessage("Звук получит выбранная в Android служба распознавания. Она может отправлять его на свои серверы и использовать интернет. WileyAI не управляет политикой этой службы. Использовать её для следующих нажатий микрофона?").setNegativeButton("Отмена", null).setPositiveButton("Использовать", (confirm,w) -> save.run()).show();
            else if (which == 2 && (android.os.Build.VERSION.SDK_INT < 31 || !android.speech.SpeechRecognizer.isOnDeviceRecognitionAvailable(activity))) ui.dialog().setMessage("Системное распознавание на устройстве недоступно. Vosk продолжит работать автономно.").setPositiveButton("Понятно", null).show();
            else if (which == 3) ui.dialog().setTitle("GigaAM v3 · экспериментально").setMessage("Офлайн-распознавание русской речи. Модель (~" + GigaAmModel.sizeText() + " МиБ) скачивается отдельно и проверяется по контрольным суммам; декодирование требует компонента sherpa-onnx. Текущий Vosk остаётся доступным, переключиться обратно можно в любой момент. Использовать GigaAM для следующих нажатий микрофона?").setNegativeButton("Отмена", null).setPositiveButton("Использовать", (confirm,w) -> save.run()).show();
            else save.run();
        }).setNegativeButton("Отмена", null).show()); parent.addView(engine);
        parent.addView(ui.text("Здесь выбирается распознавание команд. Фраза активации настраивается в разделе «Голосовой вызов».",14,ui.theme.secondary));
        renderGigaAm(parent);
        LinearLayout vosk=ui.disclosure(parent,"Vosk · русский офлайн-комплект");
        state = ui.text(models.detail(), 15, ui.theme.accentText); state.setPadding(0, ui.dp(8), 0, ui.dp(8)); vosk.addView(state);
        progress = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal); progress.setMax(100); vosk.addView(progress);
        download = ui.button("Скачать · 44,1 МиБ", this::confirmDownload); vosk.addView(download);
        pause = ui.button("Приостановить загрузку", models::pause); vosk.addView(pause);
        Switch wifi = new Switch(activity); wifi.setText("Скачивать только по Wi-Fi"); wifi.setTextColor(ui.theme.text); wifi.setMinHeight(ui.dp(56)); wifi.setChecked(preferences.getBoolean("speech_wifi_only", true));
        wifi.setOnCheckedChangeListener((button, checked) -> preferences.edit().putBoolean("speech_wifi_only", checked).apply()); ui.styleControl(wifi); vosk.addView(wifi);
        LinearLayout advanced = ui.disclosure(vosk, "Управление установкой и сведения");
        advanced.addView(ui.button("Импортировать ZIP с телефона", () -> { if (canChange() && !models.busy()) importZip.run(); }));
        discard = ui.button("Сбросить незавершённую загрузку", models::discardPartial); advanced.addView(discard);
        remove = ui.button("Удалить распознавание", () -> {
            if (canChange() && !models.busy()) ui.dialog().setTitle("Удалить распознавание?").setMessage("Голосовые команды потребуют повторной установки. Чаты сохранятся.").setNegativeButton("Отмена", null).setPositiveButton("Удалить", (d, w) -> models.remove()).show();
        }); advanced.addView(remove);
        advanced.addView(ui.button("Последняя попытка загрузки", () -> ui.dialog().setTitle("Диагностика загрузки").setMessage(models.diagnostic()).setPositiveButton("Закрыть", null).show()));
        ui.card(advanced, "Русский комплект Vosk", RussianSpeechModel.ID + "\nАрхив: 44,1 МиБ. Для безопасной установки нужно 400 МиБ свободного места. Лицензия: Apache-2.0. Сначала проверяются файл и загрузка движком; качество речи проверяется при использовании.");
        advanced.addView(ui.button("Источники и контрольные суммы", () -> ui.dialog().setTitle("Файл модели").setMessage("GitHub Releases, сервер Vosk и закреплённая копия Hugging Face. Каждый источник проверяется по тем же контрольным суммам.\n\nSHA-256: " + RussianSpeechModel.SPEC.sha256() + "\nMD5: " + RussianSpeechModel.SPEC.md5()).setPositiveButton("Закрыть", null).show()));
        refresh();
    }
    private void renderGigaAm(LinearLayout parent) {
        LinearLayout card = ui.disclosure(parent, "GigaAM v3 · экспериментальное распознавание");
        gigaAmState = ui.text(gigaAm.detail(), 15, ui.theme.accentText); gigaAmState.setPadding(0, ui.dp(8), 0, ui.dp(8)); card.addView(gigaAmState);
        gigaAmProgress = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal); gigaAmProgress.setMax(100); card.addView(gigaAmProgress);
        gigaAmDownload = ui.button("Скачать GigaAM · " + GigaAmModel.sizeText() + " МиБ", this::confirmGigaAmDownload); card.addView(gigaAmDownload);
        gigaAmPause = ui.button("Приостановить загрузку", gigaAm::pause); card.addView(gigaAmPause);
        gigaAmProbe = ui.button("Проверить модель движком", () -> {
            if (gigaAm.busy() || speech.getAsBoolean() || gigaAm.active() == null) return;
            gigaAmState.setText("Проверяю загрузку модели движком…");
            try {
                GigaAmRuntime.get(activity).probe(new java.util.concurrent.atomic.AtomicBoolean()).whenComplete((done, failure) -> activity.runOnUiThread(() -> gigaAmState.setText(failure == null ? "Движок загрузил и декодировал модель успешно." : "Проверка не прошла: " + failure.getMessage())));
            } catch (Exception problem) { gigaAmState.setText("Проверка не прошла: " + problem.getMessage()); }
        }); card.addView(gigaAmProbe);
        Button profile = ui.button("Удержание в памяти: " + profileName(), () -> {});
        profile.setOnClickListener(v -> ui.dialog().setTitle("Сколько держать модель в памяти?").setItems(new String[]{"Экономично · 1 минута", "Сбалансированно · 5 минут", "Производительно · 15 минут"}, (d, which) -> {
            preferences.edit().putString("stt_memory_profile", which == 0 ? "eco" : which == 1 ? "balanced" : "quality").apply();
            GigaAmRuntime.get(activity).profileChanged();
            profile.setText("Удержание в памяти: " + profileName());
        }).setNegativeButton("Отмена", null).show()); card.addView(profile);
        gigaAmUnload = ui.button("Выгрузить модель сейчас", () -> { GigaAmRuntime.releaseIfCreated("manual"); refresh(); }); card.addView(gigaAmUnload);
        gigaAmRuntime = ui.text(GigaAmRuntime.get(activity).diagnostic(), 14, ui.theme.secondary); gigaAmRuntime.setPadding(0, ui.dp(8), 0, 0); card.addView(gigaAmRuntime);
        LinearLayout gigaAmAdvanced = ui.disclosure(card, "Управление GigaAM");
        Switch quietSpeech = new Switch(activity);
        quietSpeech.setText("Тихие команды после голосового вызова");
        quietSpeech.setTextColor(ui.theme.text);
        quietSpeech.setMinHeight(ui.dp(56));
        quietSpeech.setChecked(preferences.getBoolean(GigaAmSileroVad.ENABLED, true));
        quietSpeech.setOnCheckedChangeListener((button, checked) ->
            preferences.edit().putBoolean(GigaAmSileroVad.ENABLED, checked).apply());
        ui.styleControl(quietSpeech);
        gigaAmAdvanced.addView(quietSpeech);
        gigaAmAdvanced.addView(ui.text("Silero определяет речь после голосового вызова. Если выключить, GigaAM будет определять речь по громкости.", 14, ui.theme.secondary));
        gigaAmAdvanced.addView(ui.button("Импортировать ZIP модели", () -> { if (canChange() && !gigaAm.busy()) gigaAmImport.run(); }));
        gigaAmRemove = ui.button("Удалить модель GigaAM", () -> {
            if (canChange() && !gigaAm.busy()) ui.dialog().setTitle("Удалить модель GigaAM?").setMessage("Экспериментальное распознавание потребует повторной загрузки. Vosk не затрагивается. Чаты сохранятся.").setNegativeButton("Отмена", null).setPositiveButton("Удалить", (d, w) -> { GigaAmRuntime.releaseIfCreated("model_removed"); gigaAm.remove(); }).show();
        }); gigaAmAdvanced.addView(gigaAmRemove);
        gigaAmAdvanced.addView(ui.button("Диагностика загрузки GigaAM", () -> ui.dialog().setTitle("Диагностика GigaAM").setMessage(gigaAm.diagnostic()).setPositiveButton("Закрыть", null).show()));
        ui.card(gigaAmAdvanced, "GigaAM v3 RNN-T", GigaAmModel.ID + "\nФайлы: " + GigaAmModel.sizeText() + " МиБ, для установки нужно 600 МиБ свободного места. Лицензия: MIT. Требуется компонент sherpa-onnx. Модель распознаёт строчные русские буквы без цифр и латиницы; иностранные названия проверяются в сравнении со старым распознавателем.");
    }
    private String profileName() {
        String profile = preferences.getString("stt_memory_profile", "balanced");
        return "eco".equals(profile) ? "экономично · 1 мин" : "quality".equals(profile) ? "производительно · 15 мин" : "сбалансированно · 5 мин";
    }
    private String engineName() {
        int selected = preferences.getInt("asr_engine", 0);
        return selected == 1 ? "Android · возможна сеть" : selected == 2 ? "Android · на устройстве" : selected == 3 ? "GigaAM v3 · экспериментально" : "Vosk · без интернета";
    }
    void refresh() {
        if (state == null) return;
        state.setText(models.active() != null && !models.busy() ? "Русское распознавание установлено" : models.detail());
        progress.setVisibility(models.busy() ? View.VISIBLE : View.GONE); progress.setIndeterminate(models.percent() < 0); if (models.percent() >= 0) progress.setProgress(models.percent());
        download.setEnabled(!models.busy()); download.setText(models.busy() ? "Загрузка и установка…" : models.active() != null ? "Переустановить комплект" : models.partialBytes() > 0 ? "Продолжить загрузку · 44,1 МиБ" : "Скачать · 44,1 МиБ");
        pause.setVisibility(models.busy() ? View.VISIBLE : View.GONE); remove.setEnabled(!models.busy() && models.removable()); discard.setEnabled(!models.busy() && models.partialBytes() > 0);
        if (gigaAmState != null) {
            gigaAmState.setText(gigaAm.active() != null && !gigaAm.busy() ? "Модель GigaAM установлена и проверена по файлам" : gigaAm.detail());
            gigaAmProgress.setVisibility(gigaAm.busy() ? View.VISIBLE : View.GONE); gigaAmProgress.setIndeterminate(gigaAm.percent() < 0); if (gigaAm.percent() >= 0) gigaAmProgress.setProgress(gigaAm.percent());
            gigaAmDownload.setEnabled(!gigaAm.busy());
            gigaAmDownload.setText(gigaAm.busy() ? "Загрузка и установка…" : gigaAm.partialBytes() > 0 ? "Продолжить загрузку GigaAM"
                : gigaAm.active() != null ? "Переустановить модель" : "Скачать GigaAM · " + GigaAmModel.sizeText() + " МиБ");
            gigaAmPause.setVisibility(gigaAm.busy() ? View.VISIBLE : View.GONE);
            gigaAmRemove.setEnabled(!gigaAm.busy() && gigaAm.removable());
            gigaAmProbe.setEnabled(!gigaAm.busy() && gigaAm.active() != null && !speech.getAsBoolean());
            gigaAmUnload.setEnabled(!speech.getAsBoolean());
            gigaAmRuntime.setText(GigaAmRuntime.get(activity).diagnostic());
        }
    }
    void confirmDownload() {
        if (!canChange()) return;
        ui.dialog().setTitle("Скачать русское распознавание?").setMessage("44,1 МиБ. Для новой установки нужно 400 МиБ свободного места.\n\nИсточники: GitHub Releases, Vosk и Hugging Face. " + (preferences.getBoolean("speech_wifi_only", true) ? "Только Wi-Fi." : "Разрешена любая сеть."))
            .setNegativeButton("Отмена", null).setPositiveButton("Скачать", (d, w) -> models.download(preferences.getBoolean("speech_wifi_only", true))).show();
    }
    void confirmGigaAmDownload() {
        if (!canChange() || gigaAm.busy()) return;
        ui.dialog().setTitle("Скачать модель GigaAM v3?").setMessage(GigaAmModel.sizeText() + " МиБ. Для новой установки нужно 600 МиБ свободного места. Источники: GitHub Releases и закреплённая копия Hugging Face. Каждый файл проверяется по SHA-256. " + (preferences.getBoolean("speech_wifi_only", true) ? "Только Wi-Fi." : "Разрешена любая сеть."))
            .setNegativeButton("Отмена", null).setPositiveButton("Скачать", (d, w) -> gigaAm.download(preferences.getBoolean("speech_wifi_only", true))).show();
    }
}
