package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.speech.tts.TextToSpeech;
import android.speech.tts.Voice;
import android.widget.*;
import java.util.List;
import java.util.Locale;
import java.util.function.Consumer;

/** A dedicated synthesis page: real engine, voice description, selection and preview. */
final class VoicePanel {
    private final Activity activity;
    private final MobileUi ui;
    private final LocalVoice voice;
    private final SharedPreferences preferences;
    private final Consumer<Boolean> readAloud;
    private final Runnable stop;
    private boolean closed;
    private LinearLayout voices;
    private TextView engine;
    VoicePanel(Activity activity, MobileUi ui, LocalVoice voice, SharedPreferences preferences, Consumer<Boolean> readAloud, Runnable stop) {
        this.activity = activity; this.ui = ui; this.voice = voice; this.preferences = preferences; this.readAloud = readAloud; this.stop = stop;
    }
    void render(LinearLayout parent) {
        Switch enabled = new Switch(activity); enabled.setText("Озвучивать ответы"); enabled.setTextColor(ui.theme.text); enabled.setTextSize(17); enabled.setMinHeight(ui.dp(52)); enabled.setChecked(preferences.getBoolean("read_aloud", false));
        enabled.setOnCheckedChangeListener((button, checked) -> readAloud.accept(checked)); parent.addView(enabled);
        engine = ui.text("Читаю установленные голоса…", 15, ui.theme.accentText); parent.addView(engine);
        parent.addView(ui.button("Выбрать движок озвучки", this::engines));
        Button speed = ui.button("Скорость: " + preferences.getFloat("offline_voice_rate", 1) + "×", () -> {});
        speed.setOnClickListener(v -> ui.dialog().setTitle("Скорость речи").setItems(new String[]{"Медленнее · 0,8×", "Обычная · 1×", "Немного быстрее · 1,1×", "Быстрее · 1,2×", "Очень быстро · 1,5×"}, (d, which) -> {
            float rate = new float[]{.8f, 1, 1.1f, 1.2f, 1.5f}[which]; preferences.edit().putFloat("offline_voice_rate", rate).apply(); speed.setText("Скорость: " + rate + "×");
        }).setNegativeButton("Отмена", null).show()); parent.addView(speed);
        Button pitch = ui.button("Высота голоса: " + preferences.getFloat("offline_voice_pitch", 1) + "×", () -> {});
        pitch.setOnClickListener(v -> ui.dialog().setTitle("Высота голоса").setItems(new String[]{"Ниже · 0,9×", "Обычная · 1×", "Выше · 1,08×", "Ещё выше · 1,16×"}, (d,which) -> { float value = new float[]{.9f,1,1.08f,1.16f}[which]; preferences.edit().putFloat("offline_voice_pitch", value).apply(); pitch.setText("Высота голоса: " + value + "×"); }).setNegativeButton("Отмена", null).show()); parent.addView(pitch);
        parent.addView(ui.button("Остановить озвучку", stop));
        voices = ui.vertical(); parent.addView(voices);
        LinearLayout advanced = ui.disclosure(parent, "Другие движки и сведения");
        advanced.addView(ui.button("Обновить список голосов", () -> voice.reload(this::refresh)));
        advanced.addView(ui.button("Добавить голоса в Android", () -> {
            try { activity.startActivity(new Intent("com.android.settings.TTS_SETTINGS")); }
            catch (Exception error) { try { activity.startActivity(new Intent(TextToSpeech.Engine.ACTION_INSTALL_TTS_DATA)); } catch (Exception missing) { ui.dialog().setMessage("Откройте настройки синтеза речи Android").setPositiveButton("Понятно", null).show(); } }
        }));
        ui.card(advanced, "Как устроена озвучка", "Это установленные голоса Android, а не языковые модели. WileyAI использует только русские голоса, которые движок помечает как доступные без сети. Тембр и пол часто не указаны системой — сравните варианты кнопкой «Прослушать». Новые голоса устанавливаются средствами выбранного движка.");
        voice.ready(this::refresh);
    }
    private void engines() {
        voice.ready(() -> {
            if (closed) return;
            List<TextToSpeech.EngineInfo> engines = voice.engines(); String[] names = new String[engines.size()];
            for (int i = 0; i < names.length; i++) names[i] = engines.get(i).label;
            ui.dialog().setTitle("Движок озвучки WileyAI").setItems(names, (d, which) -> { engine.setText("Подключаю движок…"); voice.selectEngine(engines.get(which).name, this::refresh); }).setNegativeButton("Отмена", null).show();
        });
    }
    private void refresh() {
        if (closed) return;
        List<Voice> available = voice.voices(); voices.removeAllViews(); engine.setText(voice.engineLabel() + " · голоса без интернета");
        if (available.isEmpty()) { ui.card(voices, "Русский голос не установлен", "Добавьте русский голос в настройках озвучки Android, затем обновите список."); return; }
        String selected = preferences.getString("offline_voice", ""); if (selected.isEmpty()) selected = available.get(0).getName();
        for (int i = 0; i < available.size(); i++) {
            Voice item = available.get(i); LinearLayout card = ui.vertical(); card.setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(12));
            boolean chosen = item.getName().equals(selected); card.setBackground(ui.panel(chosen ? ui.theme.high : ui.theme.low, 18));
            TextView title = ui.text(VoiceLabels.title(item.getName(), i + 1) + (chosen ? "  ✓" : ""), 18, ui.theme.accentText); card.addView(title);
            TextView description = ui.text((voice.description().isEmpty() ? voice.engineLabel() : voice.description()) + " · " + item.getLocale().getDisplayName(new Locale("ru")) + "\n" + VoiceLabels.quality(item.getQuality()), 14, ui.theme.secondary); card.addView(description);
            LinearLayout actions = ui.row();
            actions.addView(ui.button(chosen ? "Выбран" : "Выбрать", () -> { voice.select(item.getName()); refresh(); }), new LinearLayout.LayoutParams(0, -2, 1));
            actions.addView(ui.button("Прослушать", () -> voice.preview(item.getName())), new LinearLayout.LayoutParams(0, -2, 1)); card.addView(actions);
            LinearLayout info = ui.disclosure(card, "Сведения о голосе"); info.addView(ui.text("Системное имя: " + item.getName() + "\nЯзык: " + item.getLocale().toLanguageTag() + "\nГолос предоставлен установленным движком Android.", 13, ui.theme.muted));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, ui.dp(8), 0, ui.dp(8)); voices.addView(card, params);
        }
    }
    void close() { closed = true; voice.stop(); }
}
