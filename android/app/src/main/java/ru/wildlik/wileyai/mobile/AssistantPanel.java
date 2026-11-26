package ru.wildlik.wileyai.mobile;

import android.app.*;

import android.content.*;
import android.provider.Settings;
import android.widget.*;
import java.util.function.BooleanSupplier;

/** One place for system assistant role, explicit background microphone opt-in and its stop control. */
final class AssistantPanel {
    private final Activity activity; private final MobileUi ui; private final BooleanSupplier modelInstalled;
    private final RuntimeAccess access;
    private final Runnable downloadVosk, speechSettings;
    private TextView state; private Button enable, wakeEngineBtn;
    private final android.os.Handler main = new android.os.Handler(android.os.Looper.getMainLooper()); private boolean closed;
    private final Runnable polling = new Runnable() { public void run() { if (!closed) { refresh(); main.postDelayed(this,1000); } } };
    AssistantPanel(Activity activity, MobileUi ui, RuntimeAccess access, BooleanSupplier modelInstalled,
                   Runnable downloadVosk, Runnable speechSettings) {
        this.activity = activity; this.ui = ui; this.access = access; this.modelInstalled = modelInstalled;
        this.downloadVosk = downloadVosk; this.speechSettings = speechSettings;
    }

    void renderSetup(LinearLayout parent) {
        state = ui.text("", 16, ui.theme.accentText); parent.addView(state);
        ui.card(parent, "Как работает голосовой вызов", "Vosk распознаёт фразу вызова без интернета. LiveKit — экспериментальный детектор фразы. CAM++ сравнивает голос с вашим профилем и сам по себе не распознаёт слова.");
        parent.addView(ui.button("Назначить WileyAI помощником", this::role));
        wakeEngineBtn = ui.button("", this::chooseEngine);
        parent.addView(wakeEngineBtn);
        parent.addView(ui.button("Зарегистрировать мой голос · необязательно", this::enroll));
        enable = ui.button("Включить голосовую активацию", this::toggle);
        parent.addView(enable);
        parent.addView(ui.button("Проверить голосовой вызов", () -> SetupAction.show(ui, "Проверка голосового вызова",
                "Если фоновый вызов включён, закройте это сообщение и скажите настроенную фразу. Для проверки ручного вызова можно открыть голосовое окно кнопкой ниже.",
                "Вызвать сейчас", () -> { if (!WileyVoiceService.invoke()) role(); }, null, null)));
        refresh();
        main.postDelayed(polling,1000);
    }

    void render(LinearLayout parent) {
        renderSetup(parent);
        android.content.SharedPreferences preferences = activity.getSharedPreferences("wiley-mobile",0);
        Button phrase = ui.button("Фраза: «" + WakePhrase.label(preferences.getString("wake_phrase",WakeSettings.defaultPhrase(activity))) + "»", () -> {});
        phrase.setOnClickListener(v -> { String[] labels = new String[WakePhrase.PRESETS.length]; for (int i=0;i<labels.length;i++) labels[i]=WakePhrase.label(WakePhrase.PRESETS[i]); ui.dialog().setTitle("Фраза вызова").setItems(labels,(d,which) -> { String selected=WakePhrase.PRESETS[which]; preferences.edit().putString("wake_phrase",selected).apply(); phrase.setText("Фраза: «"+WakePhrase.label(selected)+"»"); HandsFreeService.reload(activity); }).setNegativeButton("Отмена",null).show(); }); parent.addView(phrase);

        parent.addView(ui.button("Разрешить микрофон",()->access.request(RuntimeAccess.Item.MIC,ui,this::refresh)));

        LinearLayout camSection = ui.disclosure(parent, "Чувствительность и фильтр владельца");
        Switch camSwitch = new Switch(activity);
        camSwitch.setText("Фильтр голоса владельца (CAM++)");
        camSwitch.setTextColor(ui.theme.text);
        camSwitch.setMinHeight(ui.dp(52));
        camSwitch.setChecked(OwnerSpeakerFilter.isEnabled(activity));
        camSwitch.setOnCheckedChangeListener((v, on) -> {
            if (on && (!WakeModelAssets.hasLiveKit(activity) || WakeSettings.wakeEngine(activity) == WakeSettings.ENGINE_VOSK
                    || !WakeModelAssets.hasCamPlus(activity) || !OwnerSpeakerFilter.hasEnrolledProfile(activity))) {
                camSwitch.setChecked(false);
                selectEngine(WakeSettings.ENGINE_LIVEKIT_V2_CAM);
                return;
            }
            OwnerSpeakerFilter.setEnabled(activity, on);
            if (WakeSettings.wakeEngine(activity) != WakeSettings.ENGINE_VOSK) {
                WakeSettings.setWakeEngine(activity, on ? WakeSettings.ENGINE_LIVEKIT_V2_CAM : WakeSettings.ENGINE_LIVEKIT_V2);
                wakeEngineBtn.setText("Движок активации: " + WakeSettings.wakeEngineLabel(WakeSettings.wakeEngine(activity)));
            }
            HandsFreeService.reload(activity);
        });
        ui.styleControl(camSwitch);
        camSection.addView(camSwitch);

        Button camThrBtn = ui.button("Чувствительность CAM++: " + String.format(java.util.Locale.ROOT, "%.2f", OwnerSpeakerFilter.threshold(activity)), () -> {});
        camThrBtn.setOnClickListener(v -> {
            float[] vals = {0.32f, 0.38f, 0.44f, 0.50f};
            String[] labels = {"Мягкая · 0.32", "Сбалансированная · 0.38 (реком.)", "Строгая · 0.44", "Очень строгая · 0.50"};
            ui.dialog().setTitle("Порог сходства CAM++").setItems(labels, (d, which) -> {
                OwnerSpeakerFilter.setThreshold(activity, vals[which]);
                camThrBtn.setText("Чувствительность CAM++: " + String.format(java.util.Locale.ROOT, "%.2f", vals[which]));
            }).setNegativeButton("Отмена", null).show();
        });
        camSection.addView(camThrBtn);

        Button lkThrBtn = ui.button("Порог LiveKit C v2: " + String.format(java.util.Locale.ROOT, "%.2f", WakeSettings.liveKitThreshold(activity)), () -> {});
        lkThrBtn.setOnClickListener(v -> {
            float[] vals = {0.95f, 0.98f, 0.99f};
            String[] labels = {"Чувствительный · 0.95", "Оптимальный · 0.98 (реком.)", "Строгий · 0.99"};
            ui.dialog().setTitle("Порог срабатывания LiveKit C v2").setItems(labels, (d, which) -> {
                WakeSettings.setLiveKitThreshold(activity, vals[which]);
                lkThrBtn.setText("Порог LiveKit C v2: " + String.format(java.util.Locale.ROOT, "%.2f", vals[which]));
                HandsFreeService.reload(activity);
            }).setNegativeButton("Отмена", null).show();
        });
        camSection.addView(lkThrBtn);

        parent.addView(ui.button("Журнал активаций и обратная связь",
                () -> activity.startActivity(new Intent(activity, WakeDiagnosticsActivity.class))));

        LinearLayout audioRoute = ui.disclosure(parent, "Эхоподавление, Bluetooth и маршруты");
        audioRoute.addView(ui.text(AudioRouteManager.routeSummary(activity), 13, ui.theme.secondary));
        ui.setting(audioRoute, "Аппаратное эхоподавление (AEC)", AudioRouteManager.isAecEnabled(activity),
                on -> AudioRouteManager.setAecEnabled(activity, on));
        ui.setting(audioRoute, "Шумоподавление микрофона (NS)", AudioRouteManager.isNsEnabled(activity),
                on -> { AudioRouteManager.setNsEnabled(activity, on); HandsFreeService.reload(activity); });
        Button bluetooth = ui.button("Bluetooth-гарнитура", () -> {});
        Runnable bluetoothLabel = () -> bluetooth.setText(AudioRouteManager.isBtScoEnabled(activity) ? "Отключить Bluetooth-гарнитуру" : "Использовать Bluetooth-гарнитуру");
        bluetoothLabel.run();
        bluetooth.setOnClickListener(v -> {
            if (AudioRouteManager.isBtScoEnabled(activity)) {
                AudioRouteManager.setBtScoEnabled(activity, false);
                bluetoothLabel.run();
            } else access.request(RuntimeAccess.Item.HEADSET, ui, () -> {
                AudioRouteManager.setBtScoEnabled(activity, true);
                bluetoothLabel.run();
            });
        });
        audioRoute.addView(bluetooth);
        ui.card(parent, "Вызов голосом", "Скажите «Вайли» или «Окей, Вайли», дождитесь сигнала и произнесите команду. Для вопросов нужна разговорная модель; команды работают без неё.");
        Switch prefix = new Switch(activity);
        prefix.setText("Слитные команды · эксперимент");
        prefix.setTextColor(ui.theme.text);
        prefix.setMinHeight(ui.dp(56));
        prefix.setChecked(preferences.getBoolean(WakeFinalPrefix.PREFERENCE,false));
        prefix.setOnCheckedChangeListener((v,on)->{
            preferences.edit().putBoolean(WakeFinalPrefix.PREFERENCE,on).apply();
            HandsFreeService.reload(activity);
        });
        ui.styleControl(prefix);
        parent.addView(prefix);
        parent.addView(ui.text("Доступно при фразе вызова «Вайли» и распознавании команд через GigaAM.",14,ui.theme.secondary));
        parent.addView(ui.button("Начать разговор", () -> { if (!WileyVoiceService.invoke(true)) role(); }));
        ui.card(parent,"Вопрос за вопросом","После ответа дождитесь короткого сигнала и задайте следующий вопрос. «Окей, Вайли, давай поговорим» включает более долгое ожидание. «Закончили» возвращает ожидание фразы вызова.");
        Switch follow = new Switch(activity);follow.setText("Ждать следующий вопрос после ответа");follow.setTextColor(ui.theme.text);follow.setMinHeight(ui.dp(56));follow.setChecked(preferences.getBoolean("assistant_followup",true));follow.setOnCheckedChangeListener((v,on)->preferences.edit().putBoolean("assistant_followup",on).apply());ui.styleControl(follow); parent.addView(follow);
        Button shortWait=ui.button("После ответа: "+preferences.getInt("followup_seconds",8)+" сек.",()->{});
        shortWait.setOnClickListener(v->ui.dialog().setTitle("Ожидание следующего вопроса").setItems(new String[]{"3 секунды","5 секунд","8 секунд","12 секунд","15 секунд"},(d,which)->{int value=new int[]{3,5,8,12,15}[which];preferences.edit().putInt("followup_seconds",value).apply();shortWait.setText("После ответа: "+value+" сек.");}).setNegativeButton("Отмена",null).show());parent.addView(shortWait);
        Button longWait=ui.button("В разговоре: "+preferences.getInt("conversation_seconds",30)+" сек.",()->{});
        longWait.setOnClickListener(v->ui.dialog().setTitle("Пауза между репликами в разговоре").setItems(new String[]{"15 секунд","30 секунд","60 секунд"},(d,which)->{int value=new int[]{15,30,60}[which];preferences.edit().putInt("conversation_seconds",value).apply();longWait.setText("В разговоре: "+value+" сек.");}).setNegativeButton("Отмена",null).show());parent.addView(longWait);
        Switch listening = new Switch(activity); listening.setText("Говорить «Слушаю» перед командой"); listening.setTextColor(ui.theme.text); listening.setMinHeight(ui.dp(56)); listening.setChecked(preferences.getBoolean("assistant_listening_prompt",true)); listening.setOnCheckedChangeListener((v,on)->preferences.edit().putBoolean("assistant_listening_prompt",on).apply()); ui.styleControl(listening); parent.addView(listening);
        Switch spoken = new Switch(activity); spoken.setText("Отвечать голосом при вызове помощника"); spoken.setTextColor(ui.theme.text); spoken.setMinHeight(ui.dp(56)); spoken.setChecked(activity.getSharedPreferences("wiley-mobile",0).getBoolean("assistant_spoken",true)); spoken.setOnCheckedChangeListener((v,on) -> activity.getSharedPreferences("wiley-mobile",0).edit().putBoolean("assistant_spoken",on).apply()); ui.styleControl(spoken); parent.addView(spoken);
        LinearLayout help = ui.disclosure(parent, "Работа в фоне и заблокированный экран");
        help.addView(ui.text("На заблокированном телефоне доступны время, дата, батарея, музыка и громкость. Для запуска приложений и разговора с историей нужно разблокировать телефон. Кнопка или жест вызова цифрового помощника работают и без постоянного прослушивания. На Samsung боковая кнопка настраивается отдельно. Android может остановить службу при принудительной остановке приложения или ограничениях батареи.",14,ui.theme.secondary));
        help.addView(ui.button("Открыть настройки батареи WileyAI", () -> { try { activity.startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.parse("package:" + activity.getPackageName()))); } catch (Exception ignored) {} }));
    }

    private void enroll() {
        if (!WakeModelAssets.hasCamPlus(activity)) {
            SetupAction.show(ui, "Голосовой профиль недоступен", "В этой сборке нет компонента CAM++. Для обычного вызова подходит Vosk.",
                    "Выбрать Vosk", () -> selectEngine(WakeSettings.ENGINE_VOSK), null, null);
        } else activity.startActivity(new Intent(activity, OwnerEnrollmentActivity.class));
    }

    private void chooseEngine() {
        String[] choices = {"Vosk · стандартный", "LiveKit · эксперимент", "LiveKit с фильтром моего голоса"};
        if (!WakeModelAssets.hasLiveKit(activity)) {
            ui.dialog().setTitle("Движок голосового вызова").setItems(new String[]{choices[0]},
                    (d, n) -> selectEngine(WakeSettings.ENGINE_VOSK)).setNegativeButton("Отмена", null).show();
        } else ui.dialog().setTitle("Движок голосового вызова").setItems(choices, (d,n) -> selectEngine(n)).setNegativeButton("Отмена", null).show();
    }

    private void selectEngine(int engine) {
        if (engine != WakeSettings.ENGINE_VOSK && !WakeModelAssets.hasLiveKit(activity)) {
            SetupAction.show(ui, "LiveKit недоступен", "В этой сборке для голосового вызова доступен Vosk.",
                    "Выбрать Vosk", () -> selectEngine(WakeSettings.ENGINE_VOSK), null, null);
            return;
        }
        if (engine == WakeSettings.ENGINE_LIVEKIT_V2_CAM && (!WakeModelAssets.hasCamPlus(activity) || !OwnerSpeakerFilter.hasEnrolledProfile(activity))) {
            SetupAction.show(ui,"Нужен голосовой профиль", "Запишите 3–5 фраз. Этот шаг можно пропустить и использовать Vosk.",
                    "Зарегистрировать голос",this::enroll,"Выбрать Vosk",()->selectEngine(WakeSettings.ENGINE_VOSK));
            return;
        }
        WakeSettings.setWakeEngine(activity,engine);
        OwnerSpeakerFilter.setEnabled(activity, engine == WakeSettings.ENGINE_LIVEKIT_V2_CAM);
        HandsFreeService.reload(activity);
        refresh();
    }

    private void toggle() {
        if (HandsFreeService.running()) { HandsFreeService.stop(activity); refresh(); return; }
        if (!WileyVoiceService.ready()) {
            SetupAction.show(ui,"Подключите цифрового помощника", "Выберите WileyAI в Android и вернитесь сюда.",
                    "Настройки Android",this::role,null,null);
            return;
        }
        String phrase = activity.getSharedPreferences("wiley-mobile",0).getString("wake_phrase",WakeSettings.defaultPhrase(activity));
        boolean liveKitReady = WakeModelAssets.liveKitEligible(activity, WakeSettings.wakeEngine(activity), phrase);
        if (!modelInstalled.getAsBoolean() && !liveKitReady) {
            SetupAction.show(ui,"Для голосового вызова нужен Vosk", "Русский комплект займёт 44,1 МиБ загрузки. Ручное распознавание через GigaAM можно использовать без Vosk.",
                    "Скачать Vosk",downloadVosk,"Распознавание речи",speechSettings);
            return;
        }
        SetupAction.show(ui,"Включить фоновый микрофон?", "WileyAI будет слушать фразу вызова на телефоне. Остановить прослушивание можно из уведомления.",
                "Включить", () -> access.request(RuntimeAccess.Item.MIC,ui,
                        () -> access.request(RuntimeAccess.Item.NOTICES,ui,this::start)),null,null);
    }
    void refresh() {
        if(state==null)return;
        boolean configured=activity.getSharedPreferences("wiley-mobile",0).getBoolean("handsfree_enabled",false);
        boolean running=HandsFreeService.running();
        String assistant=WileyVoiceService.selected(activity)?WileyVoiceService.ready()?"Помощник Android подключён.":"WileyAI выбрана, служба Android не подключена.":"WileyAI не выбрана помощником Android.";
        String mic=access.granted(RuntimeAccess.Item.MIC)?"Микрофон разрешён.":"Микрофон не разрешён.";
        String vosk=modelInstalled.getAsBoolean()?"Vosk установлен.":"Vosk для фонового вызова ещё не установлен.";
        String background=running?HandsFreeService.status():configured?"Фоновая активация включена в настройке, но служба не запущена.":"Фоновая активация выключена.";
        state.setText(assistant+"\n"+mic+"\n"+vosk+"\n"+background);
        enable.setText(running?"Остановить голосовую активацию":"Включить голосовую активацию");
        int engine=WakeSettings.wakeEngine(activity);
        wakeEngineBtn.setText(engine != WakeSettings.ENGINE_VOSK && !WakeModelAssets.hasLiveKit(activity)
                ? "Движок: LiveKit недоступен · Vosk при наличии" : "Движок: " + WakeSettings.wakeEngineLabel(engine));
    }
    void role() {
        try { activity.startActivity(new Intent(Settings.ACTION_VOICE_INPUT_SETTINGS)); }
        catch (Exception unsupported) { activity.startActivity(new Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)); }
    }
    private void start() {
        if (closed || !access.granted(RuntimeAccess.Item.MIC) || !access.granted(RuntimeAccess.Item.NOTICES)) return;
        try { activity.getSharedPreferences("wiley-mobile",0).edit().putBoolean("handsfree_enabled",true).apply(); activity.startForegroundService(new Intent(activity,HandsFreeService.class).setAction(HandsFreeService.ENABLE)); state.postDelayed(this::refresh, 1000); }
        catch (RuntimeException denied) { activity.getSharedPreferences("wiley-mobile",0).edit().putBoolean("handsfree_enabled",false).apply(); state.setText("Android запретил запуск. Откройте WileyAI и повторите включение."); }
    }
    void close() { closed = true; main.removeCallbacks(polling); }
}
