package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.SharedPreferences;
import android.widget.*;
import java.util.function.BooleanSupplier;

/** Local commands can be tried here, with the actual result on the same page. */
final class CommandPanel {
    static void render(Activity activity, MobileUi ui, LinearLayout parent, AppCatalog catalog, SharedPreferences settings, BooleanSupplier foreground) {
        TextView result = ui.text("Введите команду телефону", 14, ui.theme.secondary);
        EditText command = ui.field("Например: какая сейчас громкость?"); parent.addView(command);
        parent.addView(ui.button("Текущая громкость", () -> {
            command.setText("какая сейчас громкость?");
            new PhoneActionEngine(activity, result::setText, catalog, foreground).execute(PhoneCommands.parse("какая сейчас громкость?", true));
        }));
        parent.addView(ui.button("Выполнить команду", () -> {
            PhoneCommands.Action action = PhoneCommands.parse(command.getText().toString(), true);
            if (action == null) { result.setText("Команда не распознана. Раскройте примеры ниже."); return; }
            new PhoneActionEngine(activity, result::setText, catalog, foreground).execute(action);
        })); parent.addView(result);
        Switch automatic = new Switch(activity); automatic.setText("Выполнять голосовые команды сразу"); automatic.setTextColor(ui.theme.text); automatic.setTextSize(16); automatic.setMinHeight(ui.dp(56));
        automatic.setChecked(settings.getBoolean("voice_commands", true)); automatic.setOnCheckedChangeListener((button, checked) -> settings.edit().putBoolean("voice_commands", checked).apply()); parent.addView(automatic);
        LinearLayout examples = ui.disclosure(parent, "Примеры и ограничения");
        ui.card(examples, "Без интернета и языковой модели", "«Открой Телеграм», «открой музыку», «пауза», «следующая песня», «прибавить громкость», «сделай музыку потише», «громкость пятьдесят процентов», «сколько времени», «какая сегодня дата», «уровень заряда». Приложения и названия для голоса находятся в «Мои приложения». На Samsung панель использует шкалу 0–150: 50 из 150 — около 33% максимума. Запросы в процентах используют шкалу 0–100. Отрицательные и условные просьбы не выполняются; совпадения названий требуют выбора.");
    }
    private CommandPanel() {}
}
