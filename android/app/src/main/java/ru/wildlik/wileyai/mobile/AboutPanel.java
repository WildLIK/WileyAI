package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.provider.Settings;
import android.text.InputFilter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

final class AboutPanel {
    private final Activity activity;
    private final MobileUi ui;
    private final Consumer<byte[]> save;
    private TextView status, notes;
    private Button check, download, install;
    private boolean busy;

    AboutPanel(Activity activity, MobileUi ui, Consumer<byte[]> save) {
        this.activity = activity;
        this.ui = ui;
        this.save = save;
    }

    void render(LinearLayout cards) {
        ui.card(cards, "WileyAI " + BuildConfig.VERSION_NAME, "Номер сборки " + BuildConfig.VERSION_CODE);
        Switch automatic = new Switch(activity);
        automatic.setText("Проверять обновления автоматически");
        automatic.setTextColor(ui.theme.text);
        automatic.setChecked(ReleaseUpdates.enabled(activity));
        ui.styleControl(automatic);
        automatic.setOnCheckedChangeListener((ignored, value) -> {
            ReleaseUpdates.preferences(activity).edit().putBoolean("automatic", value).remove("last_check").apply();
            UpdateCheckJob.schedule(activity);
            if (value) refreshAfterCheck();
        });
        cards.addView(automatic);
        check = ui.button("Проверить обновления", () -> work("Проверяем GitHub…",
                () -> ReleaseUpdates.check(activity.getApplicationContext(), true)));
        cards.addView(check);
        status = ui.text("", 14, ui.theme.text);
        notes = ui.text("", 14, ui.theme.secondary);
        cards.addView(status);
        cards.addView(notes);
        download = ui.button("Скачать обновление", () -> {
            ReleaseUpdates.Offer offer = ReleaseUpdates.state().offer();
            work("Начинается загрузка…", () -> ReleaseUpdates.download(activity.getApplicationContext(), offer,
                    percent -> onUi(() -> status.setText("Скачано " + percent + "%"))));
        });
        install = ui.button("Установить обновление", this::confirmInstall);
        cards.addView(download);
        cards.addView(install);
        ui.link(cards, "Релизы на GitHub", "История изменений и файлы выпусков", () -> launch(
                new Intent(Intent.ACTION_VIEW, Uri.parse(ReleaseUpdates.PAGE))));
        ui.link(cards, "Сообщить об ошибке", "Предпросмотр и сохранение ZIP", this::feedback);
        ui.link(cards, "Срок хранения технического журнала", DiagnosticLog.retentionDays() + " дн. · до 5 МиБ", () ->
                ui.dialog().setTitle("Срок хранения")
                        .setItems(new String[]{"1 день", "7 дней", "30 дней"}, (ignored, index) -> {
                            int days = new int[]{1, 7, 30}[index];
                            DiagnosticLog.setRetentionDays(days);
                            status.setText("Журнал хранится " + days + " дн.");
                        }).show());
        refresh();
        refreshAfterCheck();
    }

    private void refreshAfterCheck() {
        if (!ReleaseUpdates.configured() || !ReleaseUpdates.enabled(activity)) return;
        var context = activity.getApplicationContext();
        ReleaseUpdates.run(() -> {
            ReleaseUpdates.check(context, false);
            onUi(() -> { if (!busy && status.isAttachedToWindow()) refresh(); });
        });
    }

    private void confirmInstall() {
        ReleaseUpdates.Offer offer = ReleaseUpdates.state().offer();
        if (offer == null) return;
        if (!activity.getPackageManager().canRequestPackageInstalls()) {
            ui.dialog().setTitle("Разрешение Android")
                    .setMessage("Чтобы передать проверенный APK системному установщику, разрешите установку из этого источника. Вернитесь и снова нажмите «Установить обновление».")
                    .setPositiveButton("Настройки Android", (dialog, button) -> launch(new Intent(
                            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + activity.getPackageName()))))
                    .setNegativeButton("Отмена", null).show();
            return;
        }
        ui.dialog().setTitle("Установить WileyAI " + offer.version() + "?")
                .setMessage("Android покажет системное подтверждение установки поверх текущей версии.")
                .setNegativeButton("Отмена", null).setPositiveButton("Продолжить", (dialog, button) ->
                        work("Повторная проверка APK…", () -> {
                            if (!ReleaseUpdates.prepareInstall(activity.getApplicationContext(), offer)) {
                                throw new IllegalArgumentException("Проверка APK не пройдена. Повторите загрузку.");
                            }
                            Uri uri = Uri.parse("content://" + activity.getPackageName() + ".updates/WileyAI-Update.apk");
                            Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, UpdateFileProvider.MIME)
                                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                            intent.setClipData(ClipData.newRawUri("Проверенный APK WileyAI", uri));
                            onUi(() -> launch(intent));
                        })).show();
    }

    private void feedback() {
        EditText description = new EditText(activity);
        description.setHint("Что случилось и как это повторить");
        description.setFilters(new InputFilter[]{new InputFilter.LengthFilter(4000)});
        description.setMinLines(3);
        description.setTextColor(ui.theme.text);
        description.setHintTextColor(ui.theme.secondary);
        ui.dialog().setTitle("Сообщить об ошибке").setView(description)
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Предпросмотр", (dialog, button) -> {
                    String text = description.getText().toString();
                    DiagnosticLog.preview(report -> {
                        if (activity.isFinishing() || activity.isDestroyed()) return;
                        String settings = "Автоматическая проверка: " + ReleaseUpdates.enabled(activity)
                                + "\nСрок хранения журнала: " + DiagnosticLog.retentionDays() + " дн.\n";
                        ScrollView scroll = new ScrollView(activity);
                        LinearLayout contents = new LinearLayout(activity);
                        contents.setOrientation(LinearLayout.VERTICAL);
                        scroll.addView(contents);
                        contents.addView(ui.text("Файлы: description.txt, settings.txt, diagnostics.txt. Проверьте описание перед сохранением.", 14, ui.theme.text));
                        contents.addView(ui.text("description.txt\n" + text + "\n\nsettings.txt\n" + settings, 14, ui.theme.text));
                        contents.addView(ui.button("Показать diagnostics.txt", () ->
                                ui.dialog().setTitle("diagnostics.txt").setMessage(report)
                                        .setPositiveButton("Закрыть", null).show()));
                        ui.dialog().setTitle("Состав отчёта").setView(scroll)
                                .setNegativeButton("Отмена", null)
                                .setPositiveButton("Сохранить ZIP", (preview, pressed) -> work("Создаём ZIP…", () -> {
                                    byte[] bytes = zip(text, settings, report);
                                    onUi(() -> save.accept(bytes));
                                })).show();
                    });
                }).show();
    }

    private static byte[] zip(String description, String settings, String diagnostics) throws Exception {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        try (ZipOutputStream archive = new ZipOutputStream(buffer)) {
            add(archive, "description.txt", description);
            add(archive, "settings.txt", settings);
            add(archive, "diagnostics.txt", diagnostics);
        }
        return buffer.toByteArray();
    }
    private static void add(ZipOutputStream archive, String name, String content) throws Exception {
        archive.putNextEntry(new ZipEntry(name));
        archive.write(content.getBytes(StandardCharsets.UTF_8));
        archive.closeEntry();
    }
    private void launch(Intent intent) {
        try { activity.startActivity(intent); }
        catch (Exception error) { ui.dialog().setMessage("Android не открыл запрошенный экран.").setPositiveButton("Закрыть", null).show(); }
    }
    private void refresh() {
        ReleaseUpdates.State state = ReleaseUpdates.state();
        ReleaseUpdates.Offer offer = state.offer();
        check.setEnabled(!busy);
        download.setVisibility(offer != null && !state.ready() ? Button.VISIBLE : Button.GONE);
        install.setVisibility(offer != null && state.ready() ? Button.VISIBLE : Button.GONE);
        download.setEnabled(!busy);
        install.setEnabled(!busy);
        if (offer != null) {
            status.setText("Доступна " + offer.version() + " · " + (offer.size() + 1048575) / 1048576 + " МиБ"
                    + (offer.date().isEmpty() ? "" : " · " + offer.date()));
            notes.setText(offer.notes());
        } else {
            status.setText(!state.error().isEmpty() ? state.error() :
                    state.checkedAt() > 0 ? "Нет доступного обновления." :
                    ReleaseUpdates.configured() ? "Проверить доступность обновлений" : "Эта сборка без доверенного ключа обновлений.");
            notes.setText("");
        }
    }
    @FunctionalInterface private interface Work { void run() throws Exception; }
    private void work(String label, Work work) {
        if (busy) return;
        busy = true;
        refresh();
        status.setText(label);
        ReleaseUpdates.run(() -> {
            String issue = null;
            try { work.run(); }
            catch (IllegalArgumentException error) { issue = error.getMessage(); }
            catch (Exception error) { issue = "Операция не завершена. Проверьте подключение и свободное место."; }
            String result = issue;
            onUi(() -> {
                busy = false;
                refresh();
                if (result != null) status.setText(result);
            });
        });
    }
    private void onUi(Runnable work) {
        activity.runOnUiThread(() -> { if (!activity.isFinishing() && !activity.isDestroyed()) work.run(); });
    }
}
