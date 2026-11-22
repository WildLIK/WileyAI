package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.Intent;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.*;
import android.widget.*;
import java.util.List;
import org.json.JSONObject;

/** Private review, explicit consent, and local SAF export for the acoustic diagnostics. */
public final class AcousticDiagnosticsActivity extends Activity {
    private static final int EXPORT = 822, EXPORT_H2 = 823;
    private TextView shadowStatus;
    private final Handler main = new Handler(Looper.getMainLooper());
    private AcousticDiagnostics diagnostics;
    private MobileUi ui;
    private LinearLayout controls;
    private TextView status;
    private Spinner form, condition;
    private CheckBox suppress;
    private MediaPlayer player;
    private java.nio.file.Path playbackFile;
    private boolean playbackLease;
    private int playbackTicket;
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (status != null) status.setText(diagnostics.status()
                    + (VoiceTelemetry.snapshot().wakeCaptureActive() && diagnostics.active() ? " · штатный микрофон активен" : ""));
            main.postDelayed(this, 500);
            if (shadowStatus != null) shadowStatus.setText(H2Shadow.status());
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        diagnostics = AcousticDiagnostics.get(this);
        ui = new MobileUi(this, new SettingsRepository(this).theme());
        controls = ui.vertical();
        controls.setPadding(ui.dp(16), ui.dp(14), ui.dp(16), ui.dp(18));
        controls.setBackgroundColor(ui.theme.base);
        ScrollView screen = new ScrollView(this);
        screen.setFillViewport(true);
        screen.addView(controls);
        setContentView(screen);
        add(ui.text("Акустическая диагностика", 22, ui.theme.text));
        status = ui.text(diagnostics.status(), 15, ui.theme.text);
        add(status);
        add(ui.text("Запись по согласию · локальные данные · микрофон WakeEngine", 14, ui.theme.secondary));
        suppress = new CheckBox(this);
        suppress.setText("Не открывать WileyAI при обнаружении");
        suppress.setTextColor(ui.theme.text);
        add(suppress);
        add(ui.button("Пассивная диагностика · 30 минут", () -> consent("passive", 30)));
        add(ui.button("Непрерывная запись · 5 минут", () -> consent("continuous", 5)));
        add(ui.button("Непрерывная запись · 10 минут", () -> consent("continuous", 10)));
        add(ui.button("Проверка голоса · 10 минут", () -> consent("guided", 10)));
        add(ui.button("Остановить диагностику", () -> diagnostics.stop("user_stop")));
        form = selector("Как произносится обращение", AcousticDiagnostics.FORMS);
        condition = selector("Условия", AcousticDiagnostics.CONDITIONS);
        add(ui.button("Отметить испытание", () -> marker(false)));
        add(ui.button("Пропущенный вызов", () -> marker(true)));
        add(ui.button("Сохранённые события", () -> review(0)));
        add(ui.button("Лимит и хранение", this::storage));
        add(ui.button("Экспорт ZIP", this::chooseExport));
        add(ui.button("Удалить все акустические данные", this::clear));
        shadowStatus = ui.text(H2Shadow.status(), 14, ui.theme.secondary);
        add(shadowStatus);
        add(ui.button("Наблюдение H2 · 5 минут", () -> ui.dialog().setTitle("Наблюдение H2")
                .setMessage("H2 получит окна уже работающего голосового вызова. Сохраняются только оценки, время и счётчики. Остановить можно в любой момент.")
                .setNegativeButton("Отмена", null).setPositiveButton("Начать", (d,w) -> H2Shadow.start(this)).show()));
        add(ui.button("Остановить H2", H2Shadow::stop));
        add(ui.button("Сохранить результат H2", () -> {
            if (!H2Shadow.report(this).getBaseFile().isFile()) { note("Сначала завершите наблюдение H2"); return; }
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("application/json").putExtra(Intent.EXTRA_LOCAL_ONLY, true)
                    .putExtra(Intent.EXTRA_TITLE, "WileyAI_H2.json");
            try { startActivityForResult(intent, EXPORT_H2); }
            catch (android.content.ActivityNotFoundException missing) { note("Сохранение недоступно"); }
        }));
    }

    private void add(android.view.View view) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = ui.dp(7);
        controls.addView(view, params);
    }
    private Spinner selector(String title, String[] options) {
        add(ui.text(title, 14, ui.theme.secondary));
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, options);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        spinner.setContentDescription(title);
        add(spinner);
        return spinner;
    }
    private void consent(String mode, int minutes) {
        if (diagnostics.active()) { note("Сначала остановите текущую диагностику"); return; }
        ui.dialog().setTitle("Согласие на запись звука")
                .setMessage("До " + minutes + " минут используется звук штатного микрофона WakeEngine. "
                        + (mode.equals("continuous") ? "Сохраняется весь доступный PCM. Голосовое окно при обнаружении отключено. "
                        : "Сохраняются до 8 секунд до события и до 3 секунд после него. ")
                        + "Запись может содержать разговоры. Убедитесь в согласии всех слышимых участников. "
                        + "Файлы находятся в приватном хранилище WileyAI. Кнопки остановки и удаления находятся здесь. "
                        + "Экспорт выполняется вручную.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Все согласны. Начать", (d, w) -> {
                    stopPlayer();
                    diagnostics.start(mode, minutes, suppress.isChecked(), form.getSelectedItemPosition(), condition.getSelectedItemPosition());
                }).show();
    }
    private void marker(boolean missed) {
        if (!diagnostics.ready()) { note("Включите акустическую диагностику"); return; }
        diagnostics.marker(missed, form.getSelectedItemPosition(), condition.getSelectedItemPosition());
        note(missed ? "Отметка пропуска добавлена" : "Отметка испытания добавлена");
    }
    private void storage() {
        LinearLayout box = ui.vertical();
        String[] labels = {"50 МиБ", "100 МиБ", "200 МиБ", "500 МиБ"};
        int[] limits = {50, 100, 200, 500};
        Spinner choose = new Spinner(this);
        choose.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
        for (int i = 0; i < limits.length; i++) if (diagnostics.limit() / (1024 * 1024) == limits[i]) choose.setSelection(i);
        box.addView(choose);
        CheckBox prune = new CheckBox(this);
        prune.setText("Удалять старые завершённые сессии при достижении лимита");
        prune.setChecked(diagnostics.prune());
        box.addView(prune);
        ui.dialog().setTitle("Лимит для новых сессий").setView(box).setNegativeButton("Отмена", null)
                .setPositiveButton("Сохранить", (d, w) -> diagnostics.settings(limits[choose.getSelectedItemPosition()], prune.isChecked())).show();
    }
    private void review(int page) {
        diagnostics.list(events -> {
            if (isFinishing() || isDestroyed()) return;
            if (events.isEmpty()) { note("Нет сохранённых событий"); return; }
            int start = Math.min(page * 40, events.size() - 1), end = Math.min(start + 40, events.size());
            String[] rows = new String[end - start];
            for (int i = start; i < end; i++) rows[i - start] = label(events.get(i));
            var dialog = ui.dialog().setTitle("События · " + (start + 1) + "–" + end + " из " + events.size())
                    .setItems(rows, (d, i) -> details(events.get(start + i), page)).setNegativeButton("Закрыть", null);
            if (end < events.size()) dialog.setNeutralButton("Старее", (d, w) -> review(page + 1));
            if (page > 0) dialog.setPositiveButton("Новее", (d, w) -> review(page - 1));
            dialog.show();
        });
    }
    private static String label(JSONObject event) {
        String kind = switch (event.optString("kind")) {
            case "continuous" -> "Непрерывная запись";
            case "voice_test" -> "Испытание";
            case "missed" -> "Пропуск";
            default -> event.optBoolean("accepted") ? "Принят Vosk" : "Отклонён Vosk";
        };
        int label = Math.max(0, Math.min(AcousticDiagnostics.LABELS.length - 1, event.optInt("label")));
        String marker = event.optBoolean("legacy_false_mark") && !event.optBoolean("label_override") ? "Ложное пробуждение" : AcousticDiagnostics.LABELS[label];
        return kind + " · " + marker + "\n" + event.optString("utc");
    }
    private void details(JSONObject event, int page) {
        LinearLayout box = ui.vertical();
        ScrollView scroll = new ScrollView(this);
        scroll.addView(box);
        String view = label(event) + "\nID " + event.optString("id");
        if (event.has("decision")) view += "\nРешение: " + event.optString("decision");
        if (event.has("audio_error")) view += "\nАудио: " + event.optString("audio_error");
        if (event.has("comment")) view += "\n" + event.optString("comment");
        for (String key : new String[]{"vosk_final", "vosk_replay", "gigaam"}) {
            JSONObject result = event.optJSONObject(key);
            if (result != null) view += "\n" + (key.equals("gigaam") ? "GigaAM" : "Vosk")
                    + ": " + result.optString("text", result.optString("status", ""))
                    + (result.has("accepted") ? " · принято: " + result.optInt("accepted") : "");
        }
        box.addView(ui.text(view, 14, ui.theme.text));
        box.addView(ui.button("Прослушать", () -> play(event)));
        box.addView(ui.button("Остановить воспроизведение", this::stopPlayer));
        box.addView(ui.button("Изменить метку и комментарий", () -> edit(event)));
        box.addView(ui.button("Повторить Vosk", () -> diagnostics.analyze(event, false, this::note)));
        box.addView(ui.button("Расшифровать GigaAM", () -> diagnostics.analyze(event, true, this::note)));
        box.addView(ui.button("Отменить анализ", diagnostics::cancelAnalysis));
        box.addView(ui.button("Удалить событие", () -> ui.dialog().setMessage(event.optString("kind").equals("continuous")
                        ? "Удалить непрерывную запись и связанные отметки?" : "Удалить это событие и его отдельный аудиофайл?")
                .setNegativeButton("Отмена", null).setPositiveButton("Удалить", (d, w) -> {
                    stopPlayer();
                    if (diagnostics.active()) note("Сначала остановите диагностику");
                    else diagnostics.remove(event, this::note);
                }).show()));
        ui.dialog().setTitle("Диагностическое событие").setView(scroll).setNegativeButton("Закрыть", null)
                .setPositiveButton("К списку", (d, w) -> { stopPlayer(); review(page); }).show();
    }
    private void edit(JSONObject event) {
        if (diagnostics.active()) { note("Сначала остановите диагностику"); return; }
        LinearLayout box = ui.vertical();
        Spinner choice = new Spinner(this);
        choice.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, AcousticDiagnostics.LABELS));
        choice.setSelection(Math.max(0, Math.min(AcousticDiagnostics.LABELS.length - 1, event.optInt("label"))));
        EditText comment = new EditText(this);
        comment.setHint("Короткий комментарий");
        comment.setText(event.optString("comment"));
        comment.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(240)});
        box.addView(choice);
        box.addView(comment);
        ui.dialog().setTitle("Разметка события").setView(box).setNegativeButton("Отмена", null)
                .setPositiveButton("Сохранить", (d, w) -> diagnostics.relabel(event, choice.getSelectedItemPosition(), comment.getText().toString(), this::note)).show();
    }
    private void play(JSONObject event) {
        if (diagnostics.active() || HandsFreeService.answering()) { note("Завершите запись или голосовой сеанс"); return; }
        stopPlayer();
        int ticket = ++playbackTicket;
        diagnostics.preparePlayback(event, path -> {
            if (ticket != playbackTicket || isFinishing() || isDestroyed() || diagnostics.active() || HandsFreeService.answering()) {
                diagnostics.closePlayback(path);
                return;
            }
            if (path == null) { note("Не удалось подготовить аудиофайл для прослушивания"); return; }
            playbackFile = path;
            playbackLease = true;
            HandsFreeService.pauseExternal(() -> {
                if (ticket != playbackTicket) return;
                try {
                    MediaPlayer media = new MediaPlayer();
                    player = media;
                    media.setDataSource(path.toString());
                    media.setOnCompletionListener(p -> stopPlayer());
                    media.setOnErrorListener((p, what, extra) -> { stopPlayer(); note("Не удалось воспроизвести файл"); return true; });
                    media.setOnPreparedListener(p -> {
                        if (player == p && ticket == playbackTicket) p.start();
                    });
                    media.prepareAsync();
                } catch (Exception failure) { stopPlayer(); note("Не удалось открыть запись"); }
            });
        });
    }
    private void stopPlayer() {
        playbackTicket++;
        if (player != null) { player.release(); player = null; }
        diagnostics.closePlayback(playbackFile);
        playbackFile = null;
        if (playbackLease) { playbackLease = false; HandsFreeService.resumeExternal(); }
    }
    private void chooseExport() {
        if (diagnostics.active()) { note("Остановите диагностику перед экспортом"); return; }
        ui.dialog().setTitle("Экспорт локальных записей")
                .setMessage("Архив может содержать голоса, разговоры, расшифровки и ваши комментарии. Выберите локальное хранилище.")
                .setNegativeButton("Отмена", null).setPositiveButton("Выбрать место", (d, w) -> {
                    Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                            .setType("application/zip").putExtra(Intent.EXTRA_LOCAL_ONLY, true)
                            .putExtra(Intent.EXTRA_TITLE, "WileyAI_Wake_Diagnostics.zip");
                    try { startActivityForResult(intent, EXPORT); } catch (RuntimeException unavailable) { note("Системный выбор файла недоступен"); }
                }).show();
    }
    private void clear() {
        ui.dialog().setMessage("Удалить все файлы акустической диагностики?")
                .setNegativeButton("Отмена", null).setPositiveButton("Удалить", (d, w) -> {
                    stopPlayer();
                    diagnostics.clear(this::note);
                }).show();
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == EXPORT_H2 && result == RESULT_OK && data != null && data.getData() != null) {
            Uri target = data.getData();
            new Thread(() -> {
                try (java.io.InputStream in = H2Shadow.report(this).openRead();
                     java.io.OutputStream out = getContentResolver().openOutputStream(target)) {
                    if (out == null) throw new java.io.IOException();
                    byte[] buffer = new byte[4096];
                    for (int n; (n=in.read(buffer))!=-1;) out.write(buffer,0,n);
                    runOnUiThread(() -> note("Результат H2 сохранён"));
                } catch (java.io.IOException | SecurityException failure) {
                    runOnUiThread(() -> note("Не удалось сохранить результат H2"));
                }
            }, "H2-export").start();
            return;
        }
        if (request != EXPORT || result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        diagnostics.export(() -> getContentResolver().openOutputStream(uri), this::note);
    }
    private void note(String message) { if (!isFinishing() && !isDestroyed()) Toast.makeText(this, message, Toast.LENGTH_SHORT).show(); }
    @Override protected void onResume() { super.onResume(); main.removeCallbacks(tick); tick.run(); }
    @Override protected void onPause() { stopPlayer(); main.removeCallbacks(tick); super.onPause(); }
}
