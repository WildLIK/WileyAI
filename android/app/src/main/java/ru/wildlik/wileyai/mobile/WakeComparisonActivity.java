package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.*;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public final class WakeComparisonActivity extends Activity {
    private static final int EXPORT = 826;
    private static final String[] CONDITIONS = {"Тихая комната", "На расстоянии или в кармане",
            "Фильм через проектор", "Видео через телефон", "Разговор рядом", "Новости", "Музыка с вокалом", "Тихий фон"};
    private static final String[] TRIALS = {"Вайли", "Уайли", "Окей, Вайли", "Окей, Уайли",
            "Вайли, сколько времени?", "Уайли, включи музыку", "Быстрая слитная команда", "Тихое полное имя",
            "Вай… (оборвать)", "Уай… (оборвать)", "Другое неполное имя", "Похожее слово без обращения"};
    private static final String[] LABELS = {"Настоящий вызов", "Ложное срабатывание", "Неоднозначно"};
    private final Handler main = new Handler(Looper.getMainLooper());
    private MobileUi ui;
    private LinearLayout box;
    private TextView status;
    private Spinner duration, condition, trial;
    private CheckBox audio;
    private Path exporting;
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            status.setText(WakeComparison.status());
            main.postDelayed(this, 500);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (state != null && state.containsKey("export"))
            exporting = WakeComparison.root(this).resolve(state.getString("export"));
        ui = new MobileUi(this, new SettingsRepository(this).theme());
        box = ui.vertical();
        box.setPadding(ui.dp(16), ui.dp(14), ui.dp(16), ui.dp(18));
        box.setBackgroundColor(ui.theme.base);
        ScrollView page = new ScrollView(this);
        page.setFillViewport(true);
        page.addView(box);
        setContentView(page);
        add(ui.text("Сравнение голосового вызова", 22, ui.theme.text));
        add(ui.text("Vosk, NEXT 12 и LiveKit C используют один микрофон. Голосовые команды во время сравнения приостановлены.", 14, ui.theme.secondary));
        status = ui.text(WakeComparison.status(), 15, ui.theme.text);
        add(status);
        duration = selector("Продолжительность", new String[]{"5 минут", "30 минут", "60 минут"});
        condition = selector("Условия сеанса", CONDITIONS);
        audio = new CheckBox(this);
        audio.setText("Сохранить звук локально в FLAC");
        audio.setTextColor(ui.theme.text);
        add(audio);
        add(ui.button("Начать сравнение", this::consent));
        add(ui.button("Остановить сравнение", () -> WakeComparison.stop("user_stop")));
        trial = selector("Произнесённая проба", TRIALS);
        add(ui.button("Отметить сразу после фразы", () -> {
            boolean saved = WakeComparison.mark("trial", "", chosen(trial));
            note(saved ? "Метка добавлена" : "Начните сравнение и дождитесь первых окон");
        }));
        add(ui.button("Отметить решения движков", this::review));
        add(ui.button("Сохранённые сеансы", this::sessions));
    }

    @Override protected void onResume() { super.onResume(); main.post(tick); }
    @Override protected void onPause() { main.removeCallbacks(tick); super.onPause(); }
    @Override protected void onSaveInstanceState(Bundle state) {
        if (exporting != null) state.putString("export", exporting.getFileName().toString());
        super.onSaveInstanceState(state);
    }

    private void add(android.view.View view) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = ui.dp(7);
        box.addView(view, params);
    }

    private Spinner selector(String title, String[] list) {
        add(ui.text(title, 14, ui.theme.secondary));
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, list);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        spinner.setContentDescription(title);
        add(spinner);
        return spinner;
    }

    private static String chosen(Spinner spinner) { return (String) spinner.getSelectedItem(); }

    private void consent() {
        boolean record = audio.isChecked();
        int minutes = new int[]{5, 30, 60}[duration.getSelectedItemPosition()];
        String room = chosen(condition);
        ui.dialog().setTitle("Начать сравнение")
                .setMessage((record ? "До " + minutes + " минут звука сохраняются локально. Получите согласие всех слышимых участников. "
                        : "Сохраняются только оценки, метки времени и счётчики. ")
                        + "Используется уже включённый фоновый вызов с фразой «Вайли». Для остановки вернитесь на этот экран.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton(record ? "Все согласны. Начать" : "Начать", (d, w) -> {
                    if (!WakeComparison.start(this, minutes, record, room)) note(WakeComparison.status());
                }).show();
    }

    private void review() {
        List<WakeComparison.Event> events = WakeComparison.recent();
        if (events.isEmpty()) { note("В текущем сеансе пока нет принятых решений"); return; }
        String[] items = events.stream().map(event -> {
            long tolerance = 9600; // Display grouping only, does not modify an engine decision.
            boolean agrees = events.stream().anyMatch(other -> event.capture() == other.capture()
                    && !event.kind().equals(other.kind()) && Math.abs(event.end() - other.end()) <= tolerance);
            return event.description() + (agrees ? " · совпадение" : " · отдельно");
        }).toArray(String[]::new);
        ui.dialog().setTitle("Последние решения").setItems(items, (d, i) ->
                ui.dialog().setTitle(items[i]).setItems(LABELS, (x, label) -> {
                    if (WakeComparison.mark("label", events.get(i).id(), LABELS[label])) note("Метка сохранена");
                }).show()).show();
    }

    private void sessions() {
        List<Path> paths;
        try {
            paths = AcousticStore.children(WakeComparison.root(this)).stream()
                    .filter(path -> Files.isRegularFile(path.resolve("session.json")))
                    .sorted((a, b) -> Long.compare(b.toFile().lastModified(), a.toFile().lastModified()))
                    .collect(java.util.stream.Collectors.toList());
        } catch (IOException error) { note("Список недоступен"); return; }
        if (paths.isEmpty()) { note("Завершённых сеансов нет"); return; }
        String[] names = paths.stream().map(path -> {
            try {
                var info = AcousticStore.read(path.resolve("session.json"));
                return info.optString("condition") + " · " + info.optString("utc") + " · "
                        + info.optLong("livekit_windows") + " окон";
            } catch (IOException invalid) { return path.getFileName().toString(); }
        }).toArray(String[]::new);
        ui.dialog().setTitle("Сохранённые сеансы").setItems(names, (d, idx) -> {
            Path session = paths.get(idx);
            ui.dialog().setTitle(names[idx]).setItems(new String[]{"Экспортировать ZIP", "Разметить решения", "Удалить этот сеанс"},
                    (dialog, action) -> {
                        if (action == 0) export(session);
                        else if (action == 1) reviewSaved(session);
                        else ui.dialog().setTitle("Удалить выбранный сеанс вместе со звуком?")
                                .setNegativeButton("Отмена", null).setPositiveButton("Удалить", (yes, key) -> {
                                    try { AcousticStore.erase(session); note("Сеанс удалён"); }
                                    catch (IOException error) { note("Не удалось удалить сеанс"); }
                                }).show();
                    }).show();
        }).show();
    }

    private void reviewSaved(Path session) {
        new Thread(() -> {
            try (var rows = Files.newBufferedReader(session.resolve("timeline.jsonl"))) {
                var events = new java.util.ArrayList<org.json.JSONObject>();
                for (String line; (line = rows.readLine()) != null;) {
                    var row = new org.json.JSONObject(line);
                    if (row.optString("type").equals("livekit") || row.optBoolean("next12")) events.add(row);
                }
                var file = session.resolve("labels.json");
                var labels = Files.isRegularFile(file) ? AcousticStore.read(file) : new org.json.JSONObject();
                runOnUiThread(() -> {
                    if (isFinishing()) return;
                    if (events.isEmpty()) { note("Принятых решений нет"); return; }
                    String[] choices = events.stream().map(row -> String.format(java.util.Locale.ROOT,
                            "%s · %.2f с · %.3f · %s", row.optString("type").equals("livekit") ? "LiveKit C"
                            : row.optBoolean("vosk") ? "Vosk + NEXT 12" : "NEXT 12", row.optLong("ms") / 1000.0,
                            row.optString("reason").equals("final_prefix") ? row.optDouble("prefix_confidence") : row.optDouble("score"),
                            labels.optString(row.optString("id"), "без метки"))).toArray(String[]::new);
                    ui.dialog().setTitle("Решения сеанса").setItems(choices, (d, i) ->
                            ui.dialog().setTitle(choices[i]).setItems(LABELS, (x, label) -> {
                                AcousticStore.set(labels, events.get(i).optString("id"), LABELS[label]);
                                try {
                                    new AcousticStore(WakeComparison.root(this)).write(file, labels);
                                    note("Метка сохранена");
                                } catch (IOException error) { note("Не удалось сохранить метку"); }
                            }).show()).show();
                });
            } catch (IOException | org.json.JSONException error) { runOnUiThread(() -> note("Журнал сеанса недоступен")); }
        }, "WakeComparison-review").start();
    }

    private void export(Path session) {
        exporting = session;
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType("application/zip").putExtra(Intent.EXTRA_LOCAL_ONLY, true)
                .putExtra(Intent.EXTRA_TITLE, "WileyAI_NEXT16_" + session.getFileName().toString().substring(0, 8) + ".zip");
        try { startActivityForResult(intent, EXPORT); }
        catch (android.content.ActivityNotFoundException error) { note("Сохранение недоступно"); }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != EXPORT || result != RESULT_OK || data == null || data.getData() == null || exporting == null) return;
        Uri destination = data.getData();
        Path session = exporting;
        exporting = null;
        new Thread(() -> {
            try (var output = getContentResolver().openOutputStream(destination, "w")) {
                WakeComparison.export(session, output);
                runOnUiThread(() -> note("ZIP сохранён"));
            } catch (IOException | SecurityException error) {
                runOnUiThread(() -> note("Не удалось сохранить ZIP"));
            }
        }, "WakeComparison-export").start();
    }

    private void note(String message) { Toast.makeText(this, message, Toast.LENGTH_SHORT).show(); }
}
