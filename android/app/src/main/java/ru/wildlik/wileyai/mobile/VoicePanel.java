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
        ui.setting(parent,"Переиспользовать подготовку голоса",preferences.getBoolean("voice_tts_reuse",true),
            on->preferences.edit().putBoolean("voice_tts_reuse",on).apply());
        parent.addView(ui.button("Оформление голосового окна",()->{
            String[] opts={"Спокойная","Стандартная","Выразительная",preferences.getBoolean("neon_logo",true)?"Анимация логотипа WL: включена":"Анимация логотипа WL: выключена","Переключить уменьшение анимаций","Предпросмотр"};
            ui.dialog().setTitle("Оформление голосового окна").setItems(opts,(d,index)->{
                if(index<3)preferences.edit().putInt("neon_intensity",index).apply();
                else if(index==3)preferences.edit().putBoolean("neon_logo",!preferences.getBoolean("neon_logo",true)).apply();
                else if(index==4)preferences.edit().putBoolean("neon_reduce",!preferences.getBoolean("neon_reduce",false)).apply();
                else activity.startActivity(new Intent(activity,NeonPreviewActivity.class));
            }).setNegativeButton("Закрыть",null).show();
        }));
        Switch enabled = new Switch(activity); enabled.setText("Озвучивать ответы"); enabled.setTextColor(ui.theme.text); enabled.setTextSize(17); enabled.setMinHeight(ui.dp(52)); enabled.setChecked(preferences.getBoolean("read_aloud", false));
        enabled.setOnCheckedChangeListener((button, checked) -> readAloud.accept(checked)); ui.styleControl(enabled); parent.addView(enabled);
        engine = ui.text("Читаю установленные голоса…", 15, ui.theme.accentText); parent.addView(engine);
        parent.addView(ui.text("Движок озвучки", 16, ui.theme.accentText));
        LinearLayout engineButtons=ui.row(); parent.addView(engineButtons);
        engineButtons.addView(ui.button("Системный", () -> {
            engine.setText("Подключаю системную озвучку…");
            voice.selectEngine("", this::refresh);
        }),new LinearLayout.LayoutParams(0,-2,1));
        engineButtons.addView(ui.button("Выбрать движок", this::engines),new LinearLayout.LayoutParams(0,-2,1));
        parent.addView(ui.text("Настройки звучания", 16, ui.theme.accentText));
        LinearLayout sound=ui.row(); parent.addView(sound);
        Button speed = ui.button("Скорость: " + preferences.getFloat("offline_voice_rate", 1) + "×", () -> {});
        speed.setOnClickListener(v -> ui.dialog().setTitle("Скорость речи").setItems(new String[]{"Медленнее · 0,8×", "Обычная · 1×", "Немного быстрее · 1,1×", "Быстрее · 1,2×", "Очень быстро · 1,5×"}, (d, which) -> {
            float rate = new float[]{.8f, 1, 1.1f, 1.2f, 1.5f}[which]; preferences.edit().putFloat("offline_voice_rate", rate).apply(); speed.setText("Скорость: " + rate + "×");
        }).setNegativeButton("Отмена", null).show()); sound.addView(speed,new LinearLayout.LayoutParams(0,-2,1));
        Button pitch = ui.button("Высота голоса: " + preferences.getFloat("offline_voice_pitch", 1) + "×", () -> {});
        pitch.setOnClickListener(v -> ui.dialog().setTitle("Высота голоса").setItems(new String[]{"Ниже · 0,9×", "Обычная · 1×", "Выше · 1,08×", "Ещё выше · 1,16×"}, (d,which) -> { float value = new float[]{.9f,1,1.08f,1.16f}[which]; preferences.edit().putFloat("offline_voice_pitch", value).apply(); pitch.setText("Высота голоса: " + value + "×"); }).setNegativeButton("Отмена", null).show()); sound.addView(pitch,new LinearLayout.LayoutParams(0,-2,1));
        parent.addView(ui.button("Остановить озвучку", stop));
        parent.addView(ui.text("Голоса выбранного движка", 16, ui.theme.accentText));
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
            Voice item=available.get(i); boolean chosen=item.getName().equals(selected);
            LinearLayout line=ui.row(); line.setPadding(ui.dp(8),ui.dp(4),ui.dp(8),ui.dp(4)); line.setBackground(ui.panel(chosen?ui.theme.high:ui.theme.low,14));
            LinearLayout info=ui.vertical(); TextView title=ui.text(VoiceLabels.title(item.getName(),i+1)+(chosen?"  ✓":""),15,ui.theme.accentText); title.setMaxLines(1); info.addView(title);
            TextView detail=ui.text(item.getLocale().getDisplayLanguage(new Locale("ru"))+" · без сети",12,ui.theme.secondary);info.addView(detail);
            info.setOnClickListener(v->ui.dialog().setTitle("Сведения о голосе").setMessage("Имя: "+item.getName()+"\nЯзык: "+item.getLocale().toLanguageTag()+"\n"+VoiceLabels.quality(item.getQuality())).setPositiveButton("Закрыть",null).show());
            line.addView(info,new LinearLayout.LayoutParams(0,-2,1));
            Button play=ui.button("▶",()->voice.preview(item.getName()));play.setContentDescription("Прослушать голос");line.addView(play,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
            Button choose=ui.button(chosen?"✓":"○",()->{voice.select(item.getName());refresh();});choose.setContentDescription(chosen?"Голос выбран":"Выбрать голос");line.addView(choose,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
            LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.setMargins(0,ui.dp(3),0,ui.dp(3));voices.addView(line,params);
        }
    }
    void close() { closed = true; voice.stop(); }
}
