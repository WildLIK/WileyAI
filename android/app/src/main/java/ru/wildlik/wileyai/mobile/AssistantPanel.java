package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.*;

import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;
import android.provider.Settings;
import android.widget.*;
import java.util.function.BooleanSupplier;

/** One place for system assistant role, explicit background microphone opt-in and its stop control. */
final class AssistantPanel {
    static final int ROLE_REQUEST = 74, PERMISSIONS = 75;
    private final Activity activity; private final MobileUi ui; private final BooleanSupplier modelInstalled;
    private TextView state; private Button enable; private boolean pending;
    private final android.os.Handler main = new android.os.Handler(android.os.Looper.getMainLooper()); private boolean closed;
    private final Runnable polling = new Runnable() { public void run() { if (!closed) { refresh(); main.postDelayed(this,1000); } } };
    AssistantPanel(Activity activity, MobileUi ui, BooleanSupplier modelInstalled) { this.activity = activity; this.ui = ui; this.modelInstalled = modelInstalled; }
    void render(LinearLayout parent) {
        state = ui.text("", 16, ui.theme.accentText); parent.addView(state);
        parent.addView(ui.button("Назначить WileyAI помощником", this::role));
        parent.addView(ui.text("В One UI: «Цифровой помощник» → шестерёнка у «Других приложений» → WileyAI.", 14, ui.theme.secondary));
        android.content.SharedPreferences preferences = activity.getSharedPreferences("wiley-mobile",0);
        Button phrase = ui.button("Фраза: «" + WakePhrase.label(preferences.getString("wake_phrase",WakePhrase.DEFAULT)) + "»", () -> {});
        phrase.setOnClickListener(v -> { String[] labels = new String[WakePhrase.PRESETS.length]; for (int i=0;i<labels.length;i++) labels[i]=WakePhrase.label(WakePhrase.PRESETS[i]); ui.dialog().setTitle("Фраза вызова").setItems(labels,(d,which) -> { String selected=WakePhrase.PRESETS[which]; preferences.edit().putString("wake_phrase",selected).apply(); phrase.setText("Фраза: «"+WakePhrase.label(selected)+"»"); HandsFreeService.reload(activity); }).setNegativeButton("Отмена",null).show(); }); parent.addView(phrase);
        ui.card(parent, "Вызов голосом", "Произнесите выбранную фразу, дождитесь короткого сигнала и скажите команду. Например: «открой Телеграм», «прибавь громкость» или обычный вопрос. Ответ прозвучит без нажатия записи. Для вопросов нужна разговорная модель; команды работают без неё.");
        enable = ui.button("Включить голосовую активацию", () -> {
            if (HandsFreeService.running()) { HandsFreeService.stop(activity); refresh(); return; }
            if (!WileyVoiceService.selected(activity)) { ui.dialog().setMessage("Сначала назначьте WileyAI цифровым помощником Android.").setPositiveButton("Назначить", (d,w) -> role()).setNegativeButton("Отмена", null).show(); return; }
            if (!WileyVoiceService.ready()) { ui.dialog().setMessage("Android ещё не подключён к службе WileyAI. Повторно выберите WileyAI в настройках цифрового помощника и вернитесь в приложение.").setPositiveButton("Настройки Android", (d,w) -> role()).setNegativeButton("Закрыть", null).show(); return; }
            if (!modelInstalled.getAsBoolean()) { ui.dialog().setMessage("Сначала установите русский комплект Vosk в «Компоненты → Распознавание речи».").setPositiveButton("Понятно", null).show(); return; }
            ui.dialog().setTitle("Включить фоновый микрофон?").setMessage("Фраза распознаётся локально. Микрофон будет работать и при закрытом экране WileyAI, с постоянным уведомлением «Остановить». Это увеличивает расход батареи. Аудиозаписи не сохраняются и не отправляются в сеть. После вызова текст запроса сохраняется в отдельном чате помощника.")
                .setNegativeButton("Отмена", null).setPositiveButton("Включить", (d,w) -> permissions()).show();
        }); parent.addView(enable);
        parent.addView(ui.button("Вызвать помощника сейчас", () -> { if (!WileyVoiceService.invoke()) role(); }));
        parent.addView(ui.button("Начать разговор", () -> { if (!WileyVoiceService.invoke(true)) role(); }));
        ui.card(parent,"Вопрос за вопросом","После ответа дождитесь короткого сигнала и задайте следующий вопрос. «Окей, Вайли, давай поговорим» включает более долгое ожидание. «Закончили» возвращает ожидание фразы вызова.");
        Switch follow = new Switch(activity);follow.setText("Ждать следующий вопрос после ответа");follow.setTextColor(ui.theme.text);follow.setMinHeight(ui.dp(56));follow.setChecked(preferences.getBoolean("assistant_followup",true));follow.setOnCheckedChangeListener((v,on)->preferences.edit().putBoolean("assistant_followup",on).apply());parent.addView(follow);
        Button shortWait=ui.button("После ответа: "+preferences.getInt("followup_seconds",8)+" сек.",()->{});
        shortWait.setOnClickListener(v->ui.dialog().setTitle("Ожидание следующего вопроса").setItems(new String[]{"3 секунды","5 секунд","8 секунд","12 секунд","15 секунд"},(d,which)->{int value=new int[]{3,5,8,12,15}[which];preferences.edit().putInt("followup_seconds",value).apply();shortWait.setText("После ответа: "+value+" сек.");}).setNegativeButton("Отмена",null).show());parent.addView(shortWait);
        Button longWait=ui.button("В разговоре: "+preferences.getInt("conversation_seconds",30)+" сек.",()->{});
        longWait.setOnClickListener(v->ui.dialog().setTitle("Пауза между репликами в разговоре").setItems(new String[]{"15 секунд","30 секунд","60 секунд"},(d,which)->{int value=new int[]{15,30,60}[which];preferences.edit().putInt("conversation_seconds",value).apply();longWait.setText("В разговоре: "+value+" сек.");}).setNegativeButton("Отмена",null).show());parent.addView(longWait);
        Switch listening = new Switch(activity); listening.setText("Говорить «Слушаю» перед командой"); listening.setTextColor(ui.theme.text); listening.setMinHeight(ui.dp(56)); listening.setChecked(preferences.getBoolean("assistant_listening_prompt",true)); listening.setOnCheckedChangeListener((v,on)->preferences.edit().putBoolean("assistant_listening_prompt",on).apply()); parent.addView(listening);
        Switch spoken = new Switch(activity); spoken.setText("Отвечать голосом при вызове помощника"); spoken.setTextColor(ui.theme.text); spoken.setMinHeight(ui.dp(56)); spoken.setChecked(activity.getSharedPreferences("wiley-mobile",0).getBoolean("assistant_spoken",true)); spoken.setOnCheckedChangeListener((v,on) -> activity.getSharedPreferences("wiley-mobile",0).edit().putBoolean("assistant_spoken",on).apply()); parent.addView(spoken);
        LinearLayout help = ui.disclosure(parent, "Работа в фоне и заблокированный экран");
        help.addView(ui.text("На заблокированном телефоне доступны время, дата, батарея, музыка и громкость. Для запуска приложений и разговора с историей нужно разблокировать телефон. Кнопка или жест вызова цифрового помощника работают и без постоянного прослушивания. На Samsung боковая кнопка настраивается отдельно. Android может остановить службу при принудительной остановке приложения или ограничениях батареи.",14,ui.theme.secondary));
        help.addView(ui.button("Открыть настройки батареи WileyAI", () -> { try { activity.startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.parse("package:" + activity.getPackageName()))); } catch (Exception ignored) {} })); refresh(); main.postDelayed(polling,1000);
    }
    void refresh() { if (state == null) return; state.setText((WileyVoiceService.selected(activity) ? WileyVoiceService.ready() ? "WileyAI назначен помощником Android.\n" : "WileyAI выбран, но служба Android не подключена. Повторите назначение.\n" : "Системный помощник ещё не WileyAI.\n") + HandsFreeService.status()); enable.setText(HandsFreeService.running() ? "Остановить голосовую активацию" : "Включить голосовую активацию"); }
    void role() {
        try { activity.startActivity(new Intent(Settings.ACTION_VOICE_INPUT_SETTINGS)); }
        catch (Exception unsupported) { activity.startActivity(new Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)); }
    }
    private void permissions() {
        java.util.List<String> missing = new java.util.ArrayList<>();
        if (activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.RECORD_AUDIO);
        if (Build.VERSION.SDK_INT >= 33 && activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.POST_NOTIFICATIONS);
        if (!missing.isEmpty()) { pending = true; activity.requestPermissions(missing.toArray(new String[0]), PERMISSIONS); } else start();
    }
    void permissionsReturned() { if (!pending) return; pending = false; if (activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED || !((NotificationManager)activity.getSystemService(Context.NOTIFICATION_SERVICE)).areNotificationsEnabled()) { ui.dialog().setMessage("Для фонового режима разрешите микрофон и уведомления WileyAI в настройках Android.").setPositiveButton("Понятно", null).show(); return; } start(); }
    private void start() {
        if (!((NotificationManager)activity.getSystemService(Context.NOTIFICATION_SERVICE)).areNotificationsEnabled()) { notificationRequired(); return; }
        try { activity.getSharedPreferences("wiley-mobile",0).edit().putBoolean("handsfree_enabled",true).apply(); activity.startForegroundService(new Intent(activity,HandsFreeService.class).setAction(HandsFreeService.ENABLE)); state.postDelayed(this::refresh, 1000); }
        catch (RuntimeException denied) { activity.getSharedPreferences("wiley-mobile",0).edit().putBoolean("handsfree_enabled",false).apply(); state.setText("Android запретил запуск. Откройте WileyAI и повторите включение."); }
    }
    private void notificationRequired() { ui.dialog().setMessage("Разрешите уведомления WileyAI в настройках Android, чтобы была доступна кнопка остановки.").setPositiveButton("Понятно", null).show(); }
    void close() { closed = true; main.removeCallbacks(polling); }
}
