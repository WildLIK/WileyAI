package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.SharedPreferences;
import android.view.View;
import android.widget.*;
import java.util.function.BooleanSupplier;

final class LlmPanel {
    private final Activity activity; private final MobileUi ui; private final LlmModels models; private final SharedPreferences settings; private final BooleanSupplier generating; private final Runnable importFile, chat;
    private TextView status; private ProgressBar progress; private Button download, pause, useModel;
    LlmPanel(Activity activity, MobileUi ui, LlmModels models, SharedPreferences settings, BooleanSupplier generating, Runnable importFile, Runnable chat) { this.activity = activity; this.ui = ui; this.models = models; this.settings = settings; this.generating = generating; this.importFile = importFile; this.chat = chat; }
    void render(LinearLayout parent) {
        ui.card(parent, "Qwen3 · 0.6B", "Локальная модель для простых вопросов. Может ошибаться.");
        status = ui.text(models.status(), 15, ui.theme.accentText); parent.addView(status);
        progress = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal); progress.setMax(100); parent.addView(progress);
        download = ui.button("Скачать · 378,3 МиБ", () -> {
            if (generating.getAsBoolean()) return;
            ui.dialog().setTitle("Установить разговорную модель?").setMessage("Qwen3 0.6B, Q4_K_M · 378,3 МиБ. Нужно 600 МиБ свободного места.\n\nИсточник: Hugging Face / unsloth, закреплённая версия. Лицензия Apache-2.0. После проверки файла приложение пробно загрузит модель на телефоне.")
                .setNegativeButton("Отмена", null).setPositiveButton("Скачать", (d,w) -> models.download(settings.getBoolean("llm_wifi_only", true))).show();
        }); parent.addView(download);
        pause = ui.button("Приостановить", models::pause); parent.addView(pause);
        Switch wifi = new Switch(activity); wifi.setText("Скачивать только по Wi-Fi"); wifi.setTextColor(ui.theme.text); wifi.setMinHeight(ui.dp(56)); wifi.setChecked(settings.getBoolean("llm_wifi_only", true)); wifi.setOnCheckedChangeListener((v,checked) -> settings.edit().putBoolean("llm_wifi_only", checked).apply()); ui.styleControl(wifi); parent.addView(wifi);
        useModel=ui.button("Использовать модель и открыть чат",chat);
        parent.addView(useModel);
        LinearLayout advanced = ui.disclosure(parent, "Файл модели и управление");
        advanced.addView(ui.button("Удержание модели в памяти",()->{
            String[] keys={"eco","balanced","quality"};String selected=settings.getString("llm_memory_profile","balanced");
            int index=selected.equals("eco")?0:selected.equals("quality")?2:1;
            ui.dialog().setTitle("Выгрузка после простоя").setSingleChoiceItems(new String[]{"Экономичный · 1 минута","Сбалансированный · 5 минут","Производительный · 15 минут"},index,(dialog,choice)->{
                settings.edit().putString("llm_memory_profile",keys[choice]).apply();LocalLlmRuntime.get(activity).profileChanged();dialog.dismiss();
            }).setNegativeButton("Закрыть",null).show();
        }));
        advanced.addView(ui.button("Диагностика локальной модели",()->ui.dialog().setTitle("Жизненный цикл GGUF").setMessage(LocalLlmRuntime.get(activity).diagnostic()+"\nВремя движка, не всей голосовой цепочки. Запросы и ответы не записываются в лог.").setPositiveButton("Закрыть",null).show()));
        advanced.addView(ui.button("Выгрузить модель из памяти",()->LocalLlmRuntime.get(activity).session.release("manual",false)));
        advanced.addView(ui.button("Импортировать GGUF с телефона", () -> { if (!models.busy() && !generating.getAsBoolean()) importFile.run(); }));
        advanced.addView(ui.button("Сбросить незавершённую загрузку", () -> { if (!models.busy() && !generating.getAsBoolean()) models.discard(); }));
        ui.card(advanced, "Поддерживаемый файл", "Qwen3-0.6B-Q4_K_M.gguf · 396 705 472 байта. Импорт принимает точный файл из каталога с проверкой SHA-256. Произвольные GGUF и большие модели пока не поддерживаются. Контекст: 2048 токенов, ответ до 256 токенов.");
        advanced.addView(ui.button("Удалить разговорную модель", () -> { if (!models.busy() && !generating.getAsBoolean()) ui.dialog().setMessage("Удалить модель? История чатов сохранится.").setNegativeButton("Отмена", null).setPositiveButton("Удалить", (d,w) -> models.remove()).show(); })); refresh();
    }
    void refresh() { if (status == null) return; status.setText(LocalLlmNative.supported() ? models.status() : "Движок недоступен для этой архитектуры телефона"); progress.setVisibility(models.busy() ? View.VISIBLE : View.GONE); progress.setIndeterminate(models.progress() < 0); if (models.progress() >= 0) progress.setProgress(models.progress()); download.setEnabled(LocalLlmNative.supported() && !models.busy()); download.setText(models.busy() ? "Загрузка и установка…" : models.active() == null ? "Скачать / продолжить · 378,3 МиБ" : "Переустановить модель"); pause.setVisibility(models.busy() ? View.VISIBLE : View.GONE); useModel.setEnabled(LocalLlmNative.supported()&&models.active()!=null&&!models.busy()); }
}
