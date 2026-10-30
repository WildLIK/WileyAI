package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public final class MainActivity extends Activity {
    private static final String STORE = "wiley-mobile";
    private static final int MIC_PERMISSION = 71;
    private static final int SPEECH_IMPORT = 72;
    private static final int LLM_IMPORT = 73;
    private static final int GATEWAY_ATTACHMENT = 76;
    private final ExecutorService io = Executors.newCachedThreadPool();
    private final AtomicBoolean chatting = new AtomicBoolean(false);
    private final AtomicBoolean pinging = new AtomicBoolean(false);
    private final Handler pingHandler = new Handler(Looper.getMainLooper());
    private final Runnable pingLoop = new Runnable() { public void run() { if (destroyed || localMode || !page.equals("chat")) return; ping(); pingHandler.postDelayed(this, 15000); } };
    private volatile JSONObject profile;
    private volatile String conversation = "";
    private String requestId = "", lastAnswer = "";
    private boolean readAloud, phoneTarget;
    private boolean localMode = true, localReady, restoreLocalDraft = true;
    private volatile boolean destroyed;
    private String page = "chat", pcDraft = "", localTitle = "Новый чат";
    private SettingsRepository settings;
    private final PcGateway gateway = new PcGateway();
    private LocalChatController localChats;
    private MobileUi ui;
    private SpeechModelManager speechModels;
    private OfflineSpeechEngine offlineSpeech;
    private SystemSpeechEngine systemSpeech;
    private LocalVoice localVoice;
    private LocalLlm localLlm;
    private CloudChat cloudChat;
    private GatewayClient gatewayChat;
    private GatewayPanel gatewayPanel;
    private BrainController brain;
    private BrainPanel brainPanel;
    private LlmModels llmModels;
    private LlmPanel llmPanel;
    private SpeechPanel speechPanel;
    private VoicePanel voicePanel;
    private AssistantPanel assistantPanel;
    private MediaPanel mediaPanel;
    private TextView componentSpeechStatus;
    private final java.util.ArrayDeque<String> screenTrail = new java.util.ArrayDeque<>();
    private AppCatalog appCatalog;
    private AppCatalogPanel appPanel;
    private boolean resumed, micForPhone;
    private final Handler draftHandler = new Handler(Looper.getMainLooper());
    private final Runnable saveDraftLater = this::saveDraft;
    private LinearLayout root, messages;
    private ScrollView scroll;
    private TextView status, title, streaming, network;
    private EditText composer;
    private Button send, record, stop;
    private Button modeSwitch;
    private MediaRecorder recorder;
    private MediaPlayer player;
    private File recording, playback;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        settings = new SettingsRepository(this);
        ui = new MobileUi(this, settings.theme());
        offlineSpeech = new OfflineSpeechEngine(this); systemSpeech = new SystemSpeechEngine(this);
        localVoice = new LocalVoice(this, settings.preferences, this::error);
        localLlm = new LocalLlm(this); cloudChat=new CloudChat(this);gatewayChat=new GatewayClient(this);
        llmModels = new LlmModels(this, () -> { if (page.equals("llm") && llmPanel != null) llmPanel.refresh(); if (page.equals("chat") && localMode && modeSwitch != null) modeSwitch.setText(phoneModeLabel()); });
        speechModels = new SpeechModelManager(this, () -> {
            if (page.equals("speech") && speechPanel != null) speechPanel.refresh();
            if (page.equals("models") && componentSpeechStatus != null) componentSpeechStatus.setText(speechModels.busy() ? "Загрузка и установка…" : speechModels.active() != null ? "Русский комплект установлен" : "Русский комплект · 44,1 МиБ");
        });
        if (Build.VERSION.SDK_INT >= 33) getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        appCatalog = new AppCatalog(this, settings.preferences, () -> { if (page.equals("apps") && appPanel != null) appPanel.refresh(); });
        brain=new BrainController(this,appCatalog);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        conversation = ""; // Start with an unsaved new chat; create it only on the first message.
        readAloud = getSharedPreferences(STORE, MODE_PRIVATE).getBoolean("read_aloud", false);
        phoneTarget = true;
        localChats = new LocalChatController(this, new LocalChatController.Listener() {
            public void render(String chatTitle, String draft, List<LocalChatRepository.Message> list, boolean hasOlder) {
                localTitle = chatTitle;
                if (!localMode || !page.equals("chat") || messages == null) return;
                messages.removeAllViews();
                if (hasOlder) messages.addView(button("Показать предыдущие сообщения", () -> { saveDraft(); localChats.loadMore(); }));
                if (list.isEmpty()) welcome();
                for (LocalChatRepository.Message item : list) addMessage(item.role(), item.content());
                title.setText(chatTitle);
                if (restoreLocalDraft) { composer.setText(draft); composer.setSelection(composer.length()); restoreLocalDraft = false; }
                note(GatewayClient.enabled(MainActivity.this)?"Gateway · локальная и серверная история":CloudChat.enabled(MainActivity.this)?"Облачный чат · история хранится на телефоне":"Телефон · история хранится на этом устройстве");
            }
            public void ready(boolean ready) { localReady = ready; if (localMode) { if (send != null) send.setEnabled(ready && !recognitionBusy() && !chatting.get()); if (ready && composer != null && !recognitionBusy() && !chatting.get()) composer.setEnabled(true); } }
            public void error(String message) { MainActivity.this.error(message); }
        });
        String profileError = null;
        try { profile = readProfile(); } catch (Exception ignored) { profile = null; profileError = "Не удалось прочитать защищённое подключение. Создайте новый код на ПК и выполните сопряжение. Сохранённые данные подключения не удалены."; }
        Uri incoming = getIntent() != null ? getIntent().getData() : null;
        if (MediaPanel.SETTINGS.equals(getIntent().getAction())) showSection("media");
        else if (HandsFreeService.SETTINGS.equals(getIntent().getAction()) || Intent.ACTION_ASSIST.equals(getIntent().getAction())) showSection("assistant");
        else if (incoming != null) showPair(incoming.toString());
        else showChat();
        if (profileError != null) error(profileError);
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (MediaPanel.SETTINGS.equals(intent.getAction())) { saveDraft(); showSection("media"); return; }
        if (HandsFreeService.SETTINGS.equals(intent.getAction()) || Intent.ACTION_ASSIST.equals(intent.getAction())) { saveDraft(); showSection("assistant"); return; }
        if (chatting.get() || recognitionBusy()) { error("Сначала завершите текущий ответ или запись и откройте ссылку подключения ещё раз."); return; }
        saveDraft();
        discardRecording();
        if (intent.getData() != null) showPair(intent.getData().toString());
    }

    @Override protected void onDestroy() {
        destroyed = true;
        if(brain!=null)brain.close();if(brainPanel!=null)brainPanel.close();
        if (mediaPanel != null) mediaPanel.close(); if (assistantPanel != null) assistantPanel.close();
        localLlm.close(); cloudChat.close();gatewayChat.close();if(gatewayPanel!=null)gatewayPanel.close();llmModels.close();
        if (voicePanel != null) voicePanel.close(); offlineSpeech.close(); systemSpeech.close(); speechModels.close(); localVoice.close(); appCatalog.close();
        pingHandler.removeCallbacks(pingLoop);
        draftHandler.removeCallbacks(saveDraftLater);
        if (recorder != null) { try { recorder.stop(); } catch (RuntimeException ignored) {} recorder.release(); recorder = null; }
        if (recording != null) recording.delete();
        releasePlayer();
        if (gateway.activeChat != null) gateway.activeChat.disconnect();
        io.shutdownNow();
        localChats.close();
        super.onDestroy();
    }
    @Override protected void onResume() { super.onResume(); resumed = true; if (assistantPanel != null) assistantPanel.refresh();if(gatewayPanel!=null)gatewayPanel.refresh();if(modeSwitch!=null&&localMode)modeSwitch.setText(phoneModeLabel());pingHandler.removeCallbacks(pingLoop); pingHandler.post(pingLoop); }
    @Override protected void onPause() { resumed = false; offlineSpeech.cancel(); systemSpeech.cancel(); localLlm.cancel(); cloudChat.cancel();localVoice.stop(); saveDraft(); discardRecording(); if (record != null) record.setText("🎙"); pingHandler.removeCallbacks(pingLoop); super.onPause(); }

    @Override protected void onSaveInstanceState(Bundle state) { saveDraft(); super.onSaveInstanceState(state); }
    private void saveDraft() {
        draftHandler.removeCallbacks(saveDraftLater);
        if (!page.equals("chat") || composer == null) return;
        if (localMode) { if (!restoreLocalDraft) localChats.saveDraft(composer.getText().toString()); }
        else { pcDraft = composer.getText().toString(); settings.preferences.edit().putString("pc_draft", pcDraft).apply(); }
    }
    private boolean recognitionBusy() { return offlineSpeech.busy() || systemSpeech.busy(); }
    private boolean canNavigate() {
        if (chatting.get()) { note("Сначала остановите ответ или дождитесь его окончания"); return false; }
        if (recorder != null) { note("Сначала завершите запись"); return false; }
        if (recognitionBusy()) { note("Сначала завершите локальное распознавание"); return false; }
        if (!localReady && localMode && page.equals("chat")) { note("Сохраняю историю…"); return false; }
        saveDraft(); return true;
    }

    private int dp(float value) { return ui.dp(value); }
    private GradientDrawable background(int color, float radius) {
        return ui.panel(color, (int) radius);
    }
    private TextView text(String value, int size, int color) {
        return ui.text(value, size, color);
    }
    private Button button(String value, Runnable action) {
        return ui.button(value, action);
    }
    private EditText field(String hint) {
        return ui.field(hint);
    }
    private LinearLayout vertical() { LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); return layout; }
    private LinearLayout row() { LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.HORIZONTAL); return layout; }
    private void padded(View view, int top) { view.setPadding(dp(16), dp(top), dp(16), dp(8)); }
    private void layout() {if(brainPanel!=null){brainPanel.close();brainPanel=null;}if(gatewayPanel!=null){gatewayPanel.close();gatewayPanel=null;} if (mediaPanel != null) { mediaPanel.close(); mediaPanel = null; } if (assistantPanel != null) { assistantPanel.close(); assistantPanel = null; } modeSwitch = null; if (!page.equals("llm")) llmPanel = null; pingHandler.removeCallbacks(pingLoop); if (!page.equals("apps")) appPanel = null; if (!page.equals("speech")) speechPanel = null; if (voicePanel != null) { voicePanel.close(); voicePanel = null; } componentSpeechStatus = null; network = null; status = null; composer = null; messages = null; send = null; root = ui.root(); }
    private void note(String message) { if (status != null) status.setText(message); }
    private void error(String message) { onUi(() -> { if (!isDestroyed() && !isFinishing()) ui.dialog().setTitle("WileyAI").setMessage(message).setPositiveButton("Понятно", null).show(); }); }
    private void background(Runnable work) { if (!destroyed) io.execute(work); }
    private void onUi(Runnable work) { runOnUiThread(() -> { if (!destroyed && !isFinishing()) work.run(); }); }

    private void saveProfile(JSONObject value) throws Exception { settings.saveProfile(value); profile = value; }
    private JSONObject readProfile() throws Exception { return settings.readProfile(); }
    private static boolean privateIp(String host) { return SettingsRepository.privateIp(host); }
    private static void validateProfile(JSONObject value, boolean token) throws Exception { SettingsRepository.validateProfile(value, token); }
    private static JSONObject parsePair(String value) throws Exception { return SettingsRepository.parsePair(value); }
    private byte[] request(JSONObject config, String path, String method, byte[] body, String contentType) throws Exception {
        if (config == null) throw new Exception("Сначала подключите компьютер в разделе «Использование ПК»");
        return gateway.request(config, path, method, body, contentType);
    }
    private byte[] jsonRequest(String path, String method, JSONObject body) throws Exception {
        return request(profile, "/api" + path, method, body == null ? null : body.toString().getBytes(StandardCharsets.UTF_8), "application/json");
    }
    private static String query(String value) throws Exception { return URLEncoder.encode(value, "UTF-8"); }
    private synchronized String ensureConversation() throws Exception {
        if (conversation.isEmpty()) {
            JSONObject created = new JSONObject(new String(jsonRequest("/conversations", "POST", new JSONObject().put("title", "Новый чат")), StandardCharsets.UTF_8));
            conversation = created.getString("id");
            getSharedPreferences(STORE, MODE_PRIVATE).edit().putString("chat", conversation).apply();
        }
        return conversation;
    }

    private void showPair(String incoming) {
        page = "pair";
        network = null;
        layout(); padded(root, 24);
        TextView heading = text("WileyAI", 30, ui.theme.text); heading.setTypeface(null, Typeface.BOLD); root.addView(heading);
        TextView description = text("Подключение к компьютеру", 19, ui.theme.accentText); description.setPadding(0, dp(10), 0, dp(10)); root.addView(description);
        TextView help = text("На компьютере откройте Настройки → Телефон, включите подключение и покажите код. Сканируйте его камерой телефона или вставьте ссылку ниже.", 15, ui.theme.secondary); root.addView(help);
        EditText link = field("wileyai://pair?…"); link.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI | InputType.TYPE_TEXT_FLAG_MULTI_LINE); link.setMinLines(3); link.setText(incoming); root.addView(link);
        Button connect = button("Подключить", () -> {
            if (!link.isEnabled()) return;
            final JSONObject next;
            try { next = parsePair(link.getText().toString()); } catch (Exception e) { error(e.getMessage()); return; }
            ui.dialog().setTitle("Подключить телефон?").setMessage("Убедитесь, что код показан в вашем WileyAI на компьютере.")
                    .setNegativeButton("Отмена", null).setPositiveButton("Подключить", (d, w) -> {
                        connectButton(false, link);
                        background(() -> {
                            try {
                                JSONObject body = new JSONObject().put("code", next.getString("code")).put("name", Build.MODEL);
                                JSONObject result = new JSONObject(new String(request(next, "/pair", "POST", body.toString().getBytes(StandardCharsets.UTF_8), "application/json"), StandardCharsets.UTF_8));
                                next.remove("code"); next.put("token", result.getString("token")); validateProfile(next, true); saveProfile(next);
                                onUi(() -> { conversation = ""; localMode = false; phoneTarget = false; showChat(); });
                            } catch (Exception e) { error(e.getMessage()); onUi(() -> connectButton(true, link)); }
                        });
                    }).show();
        });
        root.addView(connect);
        root.addView(button("Продолжить на телефоне", () -> { localMode = true; phoneTarget = true; showChat(); }));
        TextView network = text("Через мобильную сеть включите Tailscale на телефоне и компьютере. Компьютер и WileyAI должны работать.", 14, ui.theme.muted); network.setPadding(0, dp(16), 0, 0); root.addView(network);
    }
    private void connectButton(boolean enabled, EditText input) { input.setEnabled(enabled); }

    private void showChat() {
        screenTrail.clear(); page = "chat"; restoreLocalDraft = true;
        layout();
        LinearLayout header = row(); padded(header, 8); header.setGravity(Gravity.CENTER_VERTICAL);
        title = text(localMode ? localTitle : "WileyAI · ПК", 20, ui.theme.text); title.setTypeface(null, Typeface.BOLD);
        header.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        header.addView(button("Чаты", this::chooseChat), new LinearLayout.LayoutParams(dp(72), dp(48))); root.addView(header);
        Button mode = button(localMode ? phoneModeLabel() : "ПК · модель из WileyAI  ▾", this::chooseMode);
        modeSwitch = mode;
        root.addView(mode, new LinearLayout.LayoutParams(-1, dp(48)));
        network = text(localMode ? "Команды и история доступны без ПК" : "Проверка связи…", 12, ui.theme.accentText);
        padded(network, 4); root.addView(network);
        status = text(localMode ? "Открываю историю телефона…" : "Новый чат компьютера", 12, ui.theme.muted); padded(status, 0); status.setMaxLines(2); root.addView(status);
        if (!localMode) {
            LinearLayout tools = row(); padded(tools, 0);
            tools.addView(button("Задачи ПК", () -> showItems(true)), new LinearLayout.LayoutParams(0, dp(48), 1));
            tools.addView(button("Заметки ПК", () -> showItems(false)), new LinearLayout.LayoutParams(0, dp(48), 1));
            Button target = button(phoneTarget ? "Телефон" : "ПК", () -> {});
            target.setOnClickListener(v -> { phoneTarget = !phoneTarget; target.setText(phoneTarget ? "Телефон" : "ПК"); note(phoneTarget ? "Команды выполняются на телефоне" : "Команды выполняются на компьютере"); });
            tools.addView(target, new LinearLayout.LayoutParams(dp(82), dp(48))); root.addView(tools);
        }
        scroll = new ScrollView(this); scroll.setFillViewport(true); messages = vertical(); messages.setPadding(dp(16), dp(12), dp(16), dp(12)); scroll.addView(messages);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        stop = button("Остановить ответ", this::stopChat); stop.setVisibility(View.GONE); root.addView(stop);
        if(localMode&&GatewayClient.enabled(this)){
            Button attach=button("Прикрепить файл",this::pickGatewayAttachment);
            try{JSONObject selected=settings.readGateway();if(selected!=null){JSONArray pending=selected.optJSONArray("pending_attachments");if(pending!=null&&pending.length()>0)attach.setText("Файлов: "+pending.length()+" · добавить");attach.setEnabled(GatewayClient.supports(selected,"vision")||GatewayClient.supports(selected,"file_upload"));}}catch(Exception ignored){attach.setEnabled(false);}
            root.addView(attach);
        }
        LinearLayout bar = row(); padded(bar, 4);
        composer = field(localMode ? "Например: открой Telegram" : "Сообщение Уайли…"); composer.setMaxLines(4); composer.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        composer.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int count) { draftHandler.removeCallbacks(saveDraftLater); draftHandler.postDelayed(saveDraftLater, 400); }
            public void afterTextChanged(android.text.Editable text) {}
        });
        bar.addView(composer, new LinearLayout.LayoutParams(0, -2, 1));
        record = button("🎙", this::toggleRecording); record.setContentDescription("Начать или завершить запись голоса"); bar.addView(record, new LinearLayout.LayoutParams(dp(52), dp(52)));
        send = button("➤", this::send); send.setContentDescription("Отправить сообщение"); send.setTextColor(ui.theme.accentInk); send.setBackground(background(ui.theme.accent, 16)); bar.addView(send, new LinearLayout.LayoutParams(dp(52), dp(52))); root.addView(bar);
        navigation("chat");
        if (localMode) { composer.setEnabled(false); send.setEnabled(false); localChats.load(); }
        else { composer.setText(settings.preferences.getString("pc_draft", "")); if (!conversation.isEmpty()) background(this::loadMessages); pingHandler.post(pingLoop); }
    }
    private void welcome() {
        ui.card(messages, "Уайли рядом", "Откройте приложение, управляйте музыкой и громкостью — без интернета, ПК и языковой модели. Например: «открой Telegram», «пауза», «громкость 50».\n\nРусское распознавание устанавливается в разделе «Компоненты». После нажатия микрофона распознанные команды выполняются сразу; в разделе «Команды» можно включить проверку текста перед отправкой. Для разговора установите модель в «Компоненты → Разговорная модель».");
    }
    private void navigation(String current) {
        LinearLayout nav = row(); padded(nav, 4);
        String[] names = {"Чат", "Компоненты", "Команды", "Настройки"};
        String[] pages = {"chat", "models", "features", "settings"};
        for (int i = 0; i < names.length; i++) {
            final String target = pages[i];
            Button item = button(names[i], () -> { if (!canNavigate()) return; screenTrail.clear(); if (target.equals("chat")) showChat(); else showSection(target); });
            item.setPadding(dp(4), dp(2), dp(4), dp(2)); item.setTextSize(13); item.setSingleLine(true);
            item.setAutoSizeTextTypeUniformWithConfiguration(11, 13, 1, android.util.TypedValue.COMPLEX_UNIT_SP);
            item.setSelected(current.equals(target));
            if (current.equals(target)) item.setTextColor(ui.theme.accentText);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(52), 1); params.setMargins(dp(2), 0, dp(2), 0); nav.addView(item, params);
        }
        root.addView(nav);
    }
    private void chooseMode() {
        if (!canNavigate()) return;
        ui.dialog().setTitle("Где обрабатывать сообщения?")
            .setItems(new String[]{"На телефоне · локальная модель","Выбрать мозг и аккаунт","Прямой API · настройки","Дополнительно · свой Gateway","На компьютере · чат, речь, задачи и заметки"}, (d, index) -> {
                if(index>=1&&index<=3){localMode=true;phoneTarget=true;openSection(index==1?"neural":index==2?"cloud":"connections");return;}
                if (index == 4 && profile == null) { showPair(""); return; }
                if(index==0)settings.preferences.edit().putBoolean("gateway_enabled",false).putBoolean("cloud_enabled",false).putBoolean("account_enabled",false).apply();
                localMode = index == 0; phoneTarget = localMode; showChat();
            }).setNegativeButton("Отмена", null).show();
    }
    private void openSection(String target) {
        if (!canNavigate()) return; screenTrail.addLast(page); showSection(target);
    }
    @Override public void onBackPressed() { handleBack(); }
    private void handleBack() {
        if (!canNavigate()) return;
        if (!screenTrail.isEmpty()) { String previous = screenTrail.removeLast(); if (previous.equals("chat")) showChat(); else showSection(previous); }
        else if (!page.equals("chat")) showChat(); else finish();
    }
    private void showSection(String section) {
        page = section; layout();
        String heading = switch(section) {
            case "models" -> "Компоненты"; case "features" -> "Команды телефона"; case "speech" -> "Распознавание речи";
            case "neural" -> "Мозг";case "connections" -> "Подключения";case "apps" -> "Мои приложения"; case "media" -> "Музыка и YouTube"; case "assistant" -> "Голосовой помощник"; case "voice" -> "Озвучка ответов"; case "llm" -> "Разговорная модель"; case "cloud" -> "Облачные чаты"; case "pc" -> "Использование ПК"; default -> "Настройки";
        };
        LinearLayout header = row(); padded(header, 8);
        if (!screenTrail.isEmpty()) { Button back = button("‹", this::handleBack); back.setContentDescription("Назад"); header.addView(back, new LinearLayout.LayoutParams(dp(48), dp(48))); }
        header.addView(text(heading, 24, ui.theme.text), new LinearLayout.LayoutParams(0, -2, 1)); root.addView(header);
        ScrollView content = new ScrollView(this); LinearLayout cards = vertical(); padded(cards, 8); content.addView(cards);
        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1));
        switch (section) {
            case "models":
                ui.link(cards,"Мозг","Выбор модели и инструментов телефона",()->openSection("neural"));
                ui.link(cards, "Голосовой помощник", "Вызов без кнопки и работа в фоне", () -> openSection("assistant"));
                ui.link(cards, "Разговорная модель", llmModels.active() != null ? "Qwen3 0.6B · установлена" : "Чат без интернета · Qwen3 0.6B", () -> openSection("llm"));
                componentSpeechStatus = ui.link(cards, "Распознавание речи", speechModels.active() != null ? "Русский комплект установлен" : "Русский комплект · 44,1 МиБ", () -> openSection("speech"));
                ui.link(cards, "Озвучка ответов", "Голоса, прослушивание и скорость", () -> openSection("voice"));
                ui.link(cards, "Команды телефона", "Приложения, музыка и громкость", () -> openSection("features"));
                ui.link(cards, "Музыка и YouTube", "Пауза, перемотка, поиск и выбор плеера", () -> openSection("media"));
                ui.link(cards, "Облачные чаты", "Совместимый API, свои мосты и бесплатные ограничения", () -> openSection("cloud"));
                ui.link(cards, "Использование ПК", profile == null ? "Подключить WileyAI на компьютере" : "Сопряжение и проверка связи", () -> openSection("pc"));
                LinearLayout future = ui.disclosure(cards, "Что ещё появится");
                future.addView(text("Более крупные модели и устанавливаемые дополнения появятся отдельными этапами.", 14, ui.theme.secondary));
                break;
            case "media":
                mediaPanel = new MediaPanel(this, ui, appCatalog, () -> resumed && page.equals("media")); mediaPanel.render(cards); break;
            case "assistant":
                assistantPanel = new AssistantPanel(this, ui, () -> speechModels.active() != null); assistantPanel.render(cards); break;
            case "llm":
                llmPanel = new LlmPanel(this, ui, llmModels, settings.preferences, () -> localLlm.busy() || HandsFreeService.answering(), () -> {
                    Intent file = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);
                    try { startActivityForResult(file, LLM_IMPORT); } catch (Exception error) { error("Нет приложения выбора файла"); }
                }, () -> { settings.preferences.edit().putBoolean("gateway_enabled",false).putBoolean("cloud_enabled",false).putBoolean("account_enabled",false).apply();localMode = true; phoneTarget = true; showChat(); }); llmPanel.render(cards); break;
            case "speech": speechPanel = speechPanel(); speechPanel.render(cards); break;
            case "voice":
                voicePanel = new VoicePanel(this, ui, localVoice, settings.preferences, value -> {
                    readAloud = value; settings.preferences.edit().putBoolean("read_aloud", value).apply(); if (!value) { localVoice.stop(); releasePlayer(); }
                }, () -> { localVoice.stop(); releasePlayer(); });
                voicePanel.render(cards); break;
            case "features":
                ui.link(cards, "Мои приложения", "Названия для голоса и приложения по умолчанию", () -> openSection("apps"));
                ui.link(cards, "Музыка и YouTube", "Плееры, перемотка и поиск", () -> openSection("media"));
                CommandPanel.render(this, ui, cards, appCatalog, settings.preferences, () -> resumed && page.equals("features"));
                break;
            case "apps":
                appPanel = new AppCatalogPanel(this, ui, appCatalog, () -> resumed && page.equals("apps")); appPanel.render(cards); break;
            case "cloud":
                new CloudPanel(this,ui).render(cards);
                break;
            case "neural":
                brainPanel=new BrainPanel(this,ui,()->openSection("llm"),()->openSection("cloud"),()->openSection("connections"),()->{localMode=true;phoneTarget=true;});brainPanel.render(cards);break;
            case "connections":
                gatewayPanel=new GatewayPanel(this,ui,gatewayChat,()->openSection("llm"));gatewayPanel.render(cards);break;
            case "pc": renderPc(cards); break;
            default:
                ui.link(cards,"Мозг","Локальная модель, прямое облако и управление телефоном",()->openSection("neural"));
                ui.link(cards, "Голосовой помощник", "Цифровой помощник Android и голосовая активация", () -> openSection("assistant"));
                ui.link(cards, "Оформление", "Четыре темы WileyAI", this::chooseTheme);
                ui.link(cards, "Озвучка", "Выбранный голос и чтение ответов", () -> openSection("voice"));
                ui.link(cards, "Диагностика", "Телефон, память и состояние компонентов", this::showDiagnostics);
                LinearLayout privacy = ui.disclosure(cards, "Данные и безопасность");
                privacy.addView(text("Чаты телефона хранятся на устройстве. Облачный разговор включается отдельно в «Компонентах»; после включения выбранному сервису отправляются до 8 последних сообщений текущего чата. Голосовое аудио и список приложений в чат не отправляются. Чаты, задачи и заметки ПК доступны в режиме ПК. Удаление приложения средствами Android удалит локальные данные.", 14, ui.theme.secondary));
        }
        navigation(section.equals("apps") ? "features" : section.equals("neural") || section.equals("connections") || section.equals("media") || section.equals("assistant") || section.equals("speech") || section.equals("voice") || section.equals("llm") || section.equals("cloud") || section.equals("pc") ? "models" : section);
    }
    private void renderPc(LinearLayout cards) {
        status = text(profile == null ? "Компьютер ещё не подключён" : "ПК сопряжён. Связь можно проверить ниже.", 16, ui.theme.accentText); cards.addView(status);
        if (profile == null) cards.addView(button("Подключить компьютер", () -> showPair("")));
        else {
            cards.addView(button("Проверить связь с ПК", this::checkPc));
            cards.addView(button("Открыть чат ПК", () -> { localMode = false; phoneTarget = false; showChat(); }));
            LinearLayout connection = ui.disclosure(cards, "Управление подключением");
            connection.addView(button("Изменить адрес компьютера", this::editAddress));
            connection.addView(button("Подключить другой компьютер", () -> showPair("")));
            connection.addView(button("Забыть подключение", () -> ui.dialog().setTitle("Забыть этот ПК?").setMessage("История телефона сохранится. Доступ телефона также можно отозвать в WileyAI на компьютере.")
                .setNegativeButton("Отмена", null).setPositiveButton("Забыть", (d, w) -> {
                    settings.preferences.edit().remove("connection").remove("chat").remove("pc_draft").apply(); profile = null; conversation = ""; localMode = true; phoneTarget = true; showSection("pc");
                }).show()));
        }
        Button output = button(settings.preferences.getBoolean("pc_local_voice", false) ? "Ответы ПК: голос телефона" : "Ответы ПК: голос компьютера", () -> {});
        output.setOnClickListener(v -> { boolean local = !settings.preferences.getBoolean("pc_local_voice", false); settings.preferences.edit().putBoolean("pc_local_voice", local).apply(); output.setText(local ? "Ответы ПК: голос телефона" : "Ответы ПК: голос компьютера"); }); cards.addView(output);
        LinearLayout help = ui.disclosure(cards, "Как использовать ПК");
        help.addView(text("WileyAI и компьютер должны быть включены. Сопряжение выполняется по коду из «Настройки → Телефон» на ПК. В домашней сети достаточно Wi-Fi; для связи извне можно использовать Tailscale. Модель, задачи и заметки в этом режиме находятся на компьютере.", 14, ui.theme.secondary));
    }
    private void checkPc() {
        JSONObject selected = profile; if (selected == null) return; note("Проверяю связь…");
        background(() -> {
            long began = SystemClock.elapsedRealtime();
            try { request(selected, "/ping", "GET", null, "application/json"); long elapsed = SystemClock.elapsedRealtime() - began; onUi(() -> { if (page.equals("pc") && profile == selected) note("ПК доступен · " + elapsed + " мс"); }); }
            catch (Exception error) { onUi(() -> { if (page.equals("pc") && profile == selected) note("Нет связи. Проверьте WileyAI на ПК и сеть."); }); }
        });
    }
    private void showDiagnostics() {
        android.app.ActivityManager.MemoryInfo memory = new android.app.ActivityManager.MemoryInfo(); ((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getMemoryInfo(memory);
        ui.dialog().setTitle("Диагностика телефона").setMessage(Build.MANUFACTURER + " " + Build.MODEL + "\nAndroid " + Build.VERSION.RELEASE + " · API " + Build.VERSION.SDK_INT + "\nABI: " + String.join(", ", Build.SUPPORTED_ABIS) + "\nДоступно ОЗУ: " + memory.availMem / 1048576 + " МиБ\nСвободно: " + getFilesDir().getUsableSpace() / 1048576 + " МиБ\nРаспознавание: " + speechModels.detail() + "\n" + appCatalog.status()).setPositiveButton("Закрыть", null).show();
    }
    private void chooseTheme() {
        ui.dialog().setTitle("Оформление WileyAI").setItems(WileyTheme.NAMES, (d, index) -> { settings.theme(WileyTheme.IDS[index]); ui = new MobileUi(this, settings.theme()); showSection("settings"); }).setNegativeButton("Отмена", null).show();
    }
    private SpeechPanel speechPanel() {
        return new SpeechPanel(this, ui, speechModels, this::recognitionBusy, settings.preferences, () -> {
            Intent file = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE)
                .putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/octet-stream", "application/x-zip-compressed"});
            try { startActivityForResult(file, SPEECH_IMPORT); } catch (Exception e) { error("На устройстве нет приложения для выбора ZIP-файла"); }
        });
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == AssistantPanel.ROLE_REQUEST && assistantPanel != null) assistantPanel.refresh();
        if (request == SPEECH_IMPORT && result == RESULT_OK && data != null && data.getData() != null && !speechModels.busy() && !recognitionBusy()) speechModels.importZip(data.getData());
        if (request == LLM_IMPORT && result == RESULT_OK && data != null && data.getData() != null && !llmModels.busy() && !localLlm.busy()) llmModels.importFile(data.getData());
        if(request==GATEWAY_ATTACHMENT&&result==RESULT_OK&&data!=null&&data.getData()!=null){
            Uri uri=data.getData();String name="attachment",mime=getContentResolver().getType(uri);long size=-1;
            try(android.database.Cursor cursor=getContentResolver().query(uri,new String[]{android.provider.OpenableColumns.DISPLAY_NAME,android.provider.OpenableColumns.SIZE},null,null,null)){if(cursor!=null&&cursor.moveToFirst()){name=cursor.getString(0);if(!cursor.isNull(1))size=cursor.getLong(1);}}catch(Exception ignored){}
            if(size>10*1024*1024){note("Файл превышает 10 МиБ.");return;}if(mime==null){note("Не удалось определить тип файла.");return;}
            String filename=name==null?"attachment":name,contentType=mime;ui.dialog().setTitle("Загрузить вложение?").setMessage(filename+"\n"+(size<0?"Размер проверится при чтении":String.format(Locale.ROOT,"%.2f МиБ",size/1048576.0))+"\nФайл будет передан вашему Gateway. К нейросети он уйдёт после отправки сообщения.").setNegativeButton("Отмена",null).setPositiveButton("Загрузить",(d,w)->{note("Загружаю вложение…");gatewayChat.upload(uri,filename,contentType,this::note);}).show();
        }
    }
    private void pickGatewayAttachment(){
        if(chatting.get()||gatewayChat.busy()){note("Дождитесь завершения ответа.");return;}
        try{JSONObject selected=settings.readGateway();if(selected==null)return;List<String> types=new ArrayList<>();if(GatewayClient.supports(selected,"vision")){types.add("image/png");types.add("image/jpeg");types.add("image/webp");}if(GatewayClient.supports(selected,"file_upload")){types.add("application/pdf");types.add("text/plain");types.add("text/csv");types.add("application/json");types.add("application/vnd.openxmlformats-officedocument.wordprocessingml.document");}if(types.isEmpty()){note("Вложения не подтверждены этой моделью.");return;}startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,types.toArray(new String[0])),GATEWAY_ATTACHMENT);}catch(Exception invalid){note("Не удалось открыть выбор вложения.");}
    }
    private void editAddress() {
        EditText input = field("Например, 100.101.102.103"); input.setSingleLine(true); input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        ui.dialog().setTitle("Дополнительный адрес компьютера").setMessage("Укажите адрес из Tailscale, если подключаете телефон через мобильную сеть.").setView(input).setNegativeButton("Отмена", null).setPositiveButton("Сохранить", (d, w) -> {
            String host = input.getText().toString().trim();
            if (!privateIp(host)) { error("Введите IPv4-адрес локальной сети или Tailscale."); return; }
            try {
                JSONArray old = profile.getJSONArray("hosts"), hosts = new JSONArray(); hosts.put(host);
                for (int i = 0; i < old.length() && hosts.length() < 12; i++) if (!host.equals(old.getString(i))) hosts.put(old.getString(i));
                JSONObject replacement = new JSONObject(profile.toString()).put("hosts", hosts); validateProfile(replacement, true); saveProfile(replacement);
                note("Адрес сохранён. Проверяю подключение…"); if (page.equals("pc")) checkPc(); else background(this::loadInitial);
            } catch (Exception e) { error("Не удалось сохранить адрес."); }
        }).show();
    }
    private void loadInitial() {
        ping();
        if (!localMode && !conversation.isEmpty()) loadMessages();
    }
    private void ping() {
        JSONObject current = profile;
        if (current == null || localMode || !page.equals("chat") || !pinging.compareAndSet(false, true)) return;
        background(() -> {
            long began = SystemClock.elapsedRealtime();
            try {
                request(current, "/ping", "GET", null, "application/json");
                long elapsed = SystemClock.elapsedRealtime() - began;
                onUi(() -> { if (network != null && current == profile && !localMode) network.setText("Связь с ПК: " + elapsed + " мс"); });
            } catch (Exception e) { onUi(() -> { if (network != null && current == profile && !localMode) network.setText("Нет связи с ПК · телефон доступен через выбор режима"); }); }
            finally { pinging.set(false); }
        });
    }
    private void chooseChat() {
        if (recorder != null) { note("Сначала завершите запись"); return; }
        if (chatting.get()) { note("Дождитесь окончания ответа"); return; }
        if (localMode) { chooseLocalChat(); return; }
        if (!canNavigate()) return;
        final LinearLayout expected = messages;
        note("Загружаю чаты…");
        background(() -> {
            try {
                JSONArray chats = new JSONArray(new String(jsonRequest("/conversations", "GET", null), StandardCharsets.UTF_8));
                String[] choices = new String[chats.length() + 1]; choices[0] = "+ Новый чат";
                for (int i = 0; i < chats.length(); i++) choices[i + 1] = chats.getJSONObject(i).optString("title", "Чат");
                onUi(() -> { if (localMode || messages != expected) return; ui.dialog().setTitle("Чаты").setItems(choices, (dialog, which) -> background(() -> {
                    try {
                        if (which == 0) { conversation = ""; getSharedPreferences(STORE, MODE_PRIVATE).edit().remove("chat").apply(); onUi(() -> { messages.removeAllViews(); note("Новый чат"); }); return; }
                        String id = chats.getJSONObject(which - 1).getString("id");
                        conversation = id; getSharedPreferences(STORE, MODE_PRIVATE).edit().putString("chat", id).apply(); loadMessages();
                    } catch (Exception e) { error(e.getMessage()); }
                })).setNegativeButton("Закрыть", null).show(); });
            } catch (Exception e) { error(e.getMessage()); }
        });
    }
    private void chooseLocalChat() {
        if (!canNavigate()) return;
        localChats.list(chats -> {
            String[] choices = new String[chats.size() + 1]; choices[0] = "+ Новый чат";
            for (int i = 0; i < chats.size(); i++) choices[i + 1] = chats.get(i).title();
            ui.dialog().setTitle("Чаты телефона").setItems(choices, (d, index) -> {
                restoreLocalDraft = true; composer.setEnabled(false); localChats.choose(index == 0 ? "" : chats.get(index - 1).id());
            }).setNeutralButton("Текущий чат…", (d, w) -> ui.dialog().setItems(new String[]{"Переименовать", "Удалить с телефона"}, (dialog, choice) -> {
                if (choice == 0) {
                    EditText input = field("Название чата"); input.setText(localTitle);
                    ui.dialog().setTitle("Название чата").setView(input).setNegativeButton("Отмена", null).setPositiveButton("Сохранить", (confirm, which) -> {
                        if (input.getText().toString().trim().isEmpty()) { error("Введите название"); return; }
                        localChats.rename(input.getText().toString());
                    }).show();
                } else ui.dialog().setMessage("Удалить этот чат и все его сообщения с телефона?").setNegativeButton("Отмена", null).setPositiveButton("Удалить", (confirm, which) -> { restoreLocalDraft = true; localChats.delete(); }).show();
            }).setNegativeButton("Отмена", null).show()).setNegativeButton("Закрыть", null).show();
        });
    }
    private void loadMessages() {
        try {
            final String selected = conversation;
            JSONArray list = new JSONArray(new String(jsonRequest("/messages?conversation_id=" + query(selected), "GET", null), StandardCharsets.UTF_8));
            onUi(() -> {
                if (!selected.equals(conversation) || messages == null || localMode || !page.equals("chat")) return;
                messages.removeAllViews();
                for (int i = 0; i < list.length(); i++) { JSONObject item = list.optJSONObject(i); if (item != null) addMessage(item.optString("role"), item.optString("content")); }
                note("Подключена к компьютеру"); scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
            });
        } catch (Exception e) { onUi(() -> note(e.getMessage())); }
    }
    private TextView addMessage(String role, String content) {
        TextView bubble = text(content, 16, ui.theme.text); bubble.setTextIsSelectable(true); bubble.setPadding(dp(14), dp(12), dp(14), dp(12));
        bubble.setBackground(background(role.equals("user") ? ui.theme.high : ui.theme.low, 18));
        if (role.equals("assistant")) MessageRenderer.render(bubble, content);
        bubble.setOnLongClickListener(v -> {
            ui.dialog().setTitle(role.equals("user") ? "Ваше сообщение" : "Ответ Уайли")
                .setItems(role.equals("user") ? new String[]{"Копировать", "Изменить и отправить заново"} : new String[]{"Копировать"}, (d, index) -> {
                    if (index == 0) ((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(android.content.ClipData.newPlainText("WileyAI", bubble.getText()));
                    else if (!chatting.get() && composer != null) { composer.setText(content); composer.setSelection(composer.length()); composer.requestFocus(); }
                }).setNegativeButton("Закрыть", null).show(); return true;
        });
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(role.equals("user") ? dp(24) : 0, 0, role.equals("user") ? 0 : dp(16), dp(12)); messages.addView(bubble, params);
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN)); return bubble;
    }
    private void send() {
        String value = composer.getText().toString().trim();
        if (value.isEmpty() || chatting.get() || recognitionBusy() || (localMode && !localReady)) return;
        if (localMode) {
            localChats.submit(value, id -> {
                if (composer != null && composer.getText().toString().trim().equals(value)) composer.setText("");
                PhoneCommands.Action action = StructuredActionAdapter.requiresPlan(value)?null:PhoneCommands.parse(value, true);
                if (action != null) new PhoneActionEngine(this, message -> localReply(id, message), appCatalog, () -> resumed).execute(action);
                else if (new ModelManager(this).selected()!=BrainProvider.Kind.LOCAL || (llmModels.active() != null && !llmModels.busy())) generateLocal(id);
                else localReply(id, llmModels.busy() ? "Дождитесь окончания установки разговорной модели в разделе «Компоненты»." : "Для разговора установите Qwen3 в «Компоненты → Разговорная модель» или выберите ПК. Команды телефону работают без LLM. Сообщение сохранено только на телефоне.");
            });
            return;
        }
        PhoneCommands.Action local = PhoneCommands.parse(value, phoneTarget);
        if (local != null) {
            composer.setText(""); addMessage("user", value); final LinearLayout expected = messages;
            new PhoneActionEngine(this, message -> { if (messages == expected) phoneReply(message); }, appCatalog, () -> resumed).execute(local); return;
        }
        String lower = value.toLowerCase(Locale.ROOT);
        boolean explicitPc = lower.matches(".*\\s+на (?:компьютере|пк)[.! ]*$");
        boolean explicitPhone = lower.matches(".*\\s+на (?:телефоне|смартфоне)[.! ]*$");
        if (explicitPhone || (phoneTarget && !explicitPc && lower.matches("^(открой|запусти|включи|выключи|останови|поставь|сделай|убавь|прибавь|следующий|предыдущий).*"))) {
            composer.setText(""); addMessage("user", value); addMessage("assistant", "Не распознала команду телефону. Например: «открой YouTube», «пауза», «громкость 50»."); return;
        }
        if (!chatting.compareAndSet(false, true)) return;
        composer.setText(""); addMessage("user", value); streaming = addMessage("assistant", "");
        send.setEnabled(false); stop.setVisibility(View.VISIBLE); note("Уайли думает…");
        String id = UUID.randomUUID().toString().replace("-", ""); requestId = id;
        background(() -> {
            StringBuilder answer = new StringBuilder();
            boolean[] actionSpeech = {false}, forceRead = {false}; String[] spokenResult = {""}, speechPreference = {"brief"};
            try {
                final String selected = ensureConversation();
                JSONObject payload = new JSONObject().put("text", value).put("conversation_id", selected).put("request_id", id)
                        .put("document_ids", new JSONArray()).put("mode", "text").put("timezone", java.util.TimeZone.getDefault().getID());
                byte[] data = payload.toString().getBytes(StandardCharsets.UTF_8);
                gateway.stream(profile, data, new PcGateway.StreamListener() {
                    public void delta(String value) { answer.append(value); String shown = answer.toString(); onUi(() -> { if (selected.equals(conversation) && streaming != null) { streaming.setText(shown); scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN)); } }); }
                    public void stage(String value) { boolean noAnswer = answer.length() == 0; onUi(() -> { note(value); if (noAnswer && streaming != null) streaming.setText(value); }); }
                    public void done(String value) { if (value != null) { answer.setLength(0); answer.append(value); } }
                    public void speechMode(String mode, String preference) { forceRead[0] = "read_full".equals(mode); actionSpeech[0] = "action".equals(mode) || forceRead[0]; speechPreference[0] = forceRead[0] ? "brief" : preference; }
                    public void speechResult(String value) { spokenResult[0] = value; }
                });
                lastAnswer = answer.toString();
                onUi(() -> { if (selected.equals(conversation) && streaming != null) MessageRenderer.render(streaming, lastAnswer); note("Ответ получен"); });
                String speech = actionSpeech[0] ? ("off".equals(speechPreference[0]) ? "" : "full".equals(speechPreference[0]) ? lastAnswer : spokenResult[0]) : lastAnswer;
                if ((readAloud || forceRead[0]) && !speech.isEmpty() && selected.equals(conversation) && resumed) {
                    if (settings.preferences.getBoolean("pc_local_voice", false)) { String spoken = speech; onUi(() -> { if (resumed && selected.equals(conversation)) localVoice.speak(spoken); }); }
                    else speak(speech);
                }
            } catch (Exception e) { onUi(() -> { note(e.getMessage()); if (streaming != null && answer.length() == 0) streaming.setText(e.getMessage()); }); }
            finally { gateway.activeChat = null; chatting.set(false); requestId = ""; onUi(() -> { if (send != null) send.setEnabled(true); if (stop != null) stop.setVisibility(View.GONE); }); }
        });
    }
    private void stopChat() {
        if(brain!=null&&brain.busy()){brain.cancel();note("Останавливаю план…");return;}
        if(gatewayChat.busy()){gatewayChat.cancelPending(this::note);note("Останавливаю ответ Gateway…");return;}
        if(cloudChat.busy()){cloudChat.cancel();note("Останавливаю облачный ответ…");return;}
        if (localLlm.busy()) { localLlm.cancel(); note("Останавливаю локальный ответ…"); return; }
        String id = requestId; if (id.isEmpty()) return;
        note("Останавливаю ответ…");
        background(() -> { try { jsonRequest("/chat/stop", "POST", new JSONObject().put("request_id", id)); } catch (Exception e) { onUi(() -> note(e.getMessage())); } });
    }

    private void phoneReply(String message) { addMessage("assistant", message); note("Команда телефона · локально, без сохранения в истории"); }
    private void generateLocal(String id) {
        if (HandsFreeService.answering()) { localReply(id, "Дождитесь окончания голосового ответа помощника."); return; }
        if (!chatting.compareAndSet(false, true)) return;
        stop.setVisibility(View.VISIBLE); send.setEnabled(false); composer.setEnabled(false);
        localChats.context(id, context -> {
            if (destroyed) return;
            ModelManager modelManager=new ModelManager(this);
            if(modelManager.toolsAllowed()||modelManager.selected()==BrainProvider.Kind.ACCOUNT_OAUTH){
                streaming=addMessage("assistant","Понимаю просьбу…");
                brain.generate(context,new BrainController.Host(){
                    public boolean active(){return !destroyed;}
                    public void state(String text){note(text);}
                    public void confirm(String plan,java.util.function.Consumer<Boolean> reply){if(!resumed||destroyed){reply.accept(false);return;}ui.dialog().setTitle("Выполнить план?").setMessage(plan).setNegativeButton("Отмена",(d,w)->reply.accept(false)).setOnCancelListener(d->reply.accept(false)).setPositiveButton("Выполнить",(d,w)->reply.accept(true)).show();}
                    public void launch(Intent intent){if(destroyed||((android.app.KeyguardManager)getSystemService(KEYGUARD_SERVICE)).isDeviceLocked())throw new IllegalStateException();startActivity(intent);}
                    public void done(String text){localReply(id,text);}
                    public void error(String text){localReply(id,text);}
                    public void finished(){finishLocalAnswer();}
                });return;
            }
            if (!GatewayClient.enabled(this)&&!CloudChat.enabled(this) && !context.isEmpty() && context.get(context.size() - 1).content().length() > 2000) { localReply(id, "Сократите сообщение до 2000 символов для этой модели."); finishLocalAnswer(); return; }
            boolean cloud=CloudChat.enabled(this);
            boolean remote=GatewayClient.enabled(this);
            streaming = addMessage("assistant", remote?"Отвечаю через WileyAI Gateway…":cloud?"Отвечаю через выбранный сервис…":"Загружаю модель телефона…");
            LocalLlm.Listener listener = new LocalLlm.Listener() {
                public void state(String text) { note(text); }
                public void partial(String text) { if (streaming != null) { streaming.setText(text); scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN)); } }
                public void done(String text, boolean stopped) { if(remote&&gatewayChat.savedResponse()){localChats.load();if(readAloud&&resumed&&localMode)localVoice.speak(text);}else localReply(id, text.isEmpty() ? "Ответ остановлен или не получен. Попробуйте короткий вопрос." : text + (stopped ? "\n\n[Ответ остановлен]" : "")); }
                public void error(String text) { localReply(id, text); }
                public void finished() { finishLocalAnswer(); }
            };
            if(remote)gatewayChat.generate(id,context,listener);else if(cloud)cloudChat.generate(context,listener);else localLlm.generate(llmModels.active(),LocalLlm.prompt(context),listener);
        });
    }
    private String phoneModeLabel(){if(new ModelManager(this).selected()==BrainProvider.Kind.ACCOUNT_OAUTH)return new ModelManager(this).label()+"  ▾";if(GatewayClient.enabled(this)){try{JSONObject selected=settings.readGateway();return selected==null?"Gateway · настройка  ▾":selected.optString("provider_name","Gateway")+" · "+selected.optString("model_name","выберите модель")+"  ▾";}catch(Exception ignored){return "Gateway · проверить подключение  ▾";}}if(CloudChat.enabled(this))return "Телефон · облачный чат  ▾";return llmModels.active()!=null?"Телефон · Qwen3 0.6B  ▾":"Телефон · без разговорной модели  ▾";}
    private void finishLocalAnswer() { chatting.set(false); if (send != null) send.setEnabled(localReady); if (composer != null) composer.setEnabled(localReady); if (stop != null) stop.setVisibility(View.GONE); note("Готово · "+new ModelManager(this).label()); }
    private void localReply(String id, String message) { localChats.reply(id, message); if (readAloud && resumed && localMode) localVoice.speak(message); }
    private void toggleRecording() {
        if (HandsFreeService.running()) { WileyVoiceService.invoke(); return; }
        if (recognitionBusy()) { if (systemSpeech.busy()) systemSpeech.finish(); else offlineSpeech.finish(); note("Завершаю распознавание…"); return; }
        if (recorder != null) { finishRecording(); return; }
        if (localMode && settings.preferences.getInt("asr_engine", 0) == 0 && (speechModels.active() == null || speechModels.busy())) { ui.dialog().setTitle("Русский голосовой комплект").setMessage(speechModels.busy() ? "Дождитесь установки или остановите её в разделе «Компоненты»." : "Установите русский комплект в разделе «Компоненты». Он занимает 44,1 МиБ для загрузки и не требует разговорной LLM. Текстовые команды уже доступны без установки.").setPositiveButton("Понятно", null).show(); return; }
        if (!localMode && profile == null) { showPair(""); return; }
        if (chatting.get()) { note("Дождитесь ответа перед записью"); return; }
        micForPhone = localMode;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MIC_PERMISSION); return; }
        if (localMode) beginLocalRecognition(); else beginRecording();
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == AssistantPanel.PERMISSIONS) { if (assistantPanel != null) assistantPanel.permissionsReturned(); return; }
        if (code == MIC_PERMISSION && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED && page.equals("chat")) {
            if (micForPhone && localMode) beginLocalRecognition(); else if (!micForPhone && !localMode && profile != null) beginRecording();
        }
        else if (code == MIC_PERMISSION) note("Разрешите микрофон в настройках Android");
    }
    private void beginLocalRecognition() {
        if (!localMode || destroyed || !page.equals("chat")) return;
        final int asrEngine = settings.preferences.getInt("asr_engine", 0);
        if (asrEngine == 0 && (speechModels.active() == null || speechModels.busy())) return;
        localVoice.stop(); releasePlayer();
        final EditText destination = composer;
        final String previous = composer.getText().toString();
        final String generation = asrEngine == 0 ? speechModels.active().getFileName().toString() : "android-system";
        record.setText("■"); send.setEnabled(false); composer.setEnabled(false);
        OfflineSpeechEngine.Listener recognition = new OfflineSpeechEngine.Listener() {
            public void ready(Runnable startMicrophone){
                if(!resumed||composer!=destination)return;
                if(!settings.preferences.getBoolean("assistant_listening_prompt",true)){startMicrophone.run();return;}
                java.util.concurrent.atomic.AtomicBoolean once=new java.util.concurrent.atomic.AtomicBoolean();
                Runnable begin=()->{if(!destroyed&&resumed&&composer==destination&&once.compareAndSet(false,true)){localVoice.stop();pingHandler.postDelayed(startMicrophone,160);}};
                localVoice.speakCompleted("Слушаю",begin);pingHandler.postDelayed(begin,5000);
            }
            public void state(String message) { note(message); }
            public void partial(String text) { note("Слышу: " + text); }
            public void result(String text) {
                if (!resumed || !localMode || composer != destination) return;
                if (text.isEmpty()) { note("Речь не распознана. Попробуйте ещё раз."); return; }
                settings.preferences.edit().putString("speech_verified_generation", generation).putLong("speech_verified_at", System.currentTimeMillis()).apply();
                composer.setText(previous.trim().isEmpty() ? text : previous + " " + text); composer.setSelection(composer.length());
                note(asrEngine == 0 ? "Распознано локально. Проверьте текст." : "Распознано Android. Проверьте текст.");
                if (previous.trim().isEmpty() && settings.preferences.getBoolean("voice_commands", true) && PhoneCommands.parse(text, true) != null) send();
            }
            public void error(String message) { note(message); }
            public void finished() { if (record != null) record.setText("🎙"); if (composer != null && localReady) composer.setEnabled(true); if (send != null) send.setEnabled(localReady && !chatting.get()); }
        };
        if (asrEngine == 0) offlineSpeech.start(speechModels.active(), recognition); else systemSpeech.start(asrEngine == 2, recognition);
    }
    private void beginRecording() {
        if (destroyed || localMode || profile == null || !page.equals("chat")) return;
        try {
            recording = File.createTempFile("wiley-record-", ".m4a", getCacheDir());
            recorder = new MediaRecorder(); recorder.setAudioSource(MediaRecorder.AudioSource.MIC); recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC); recorder.setAudioSamplingRate(16000); recorder.setAudioEncodingBitRate(64000);
            recorder.setOutputFile(recording.getAbsolutePath()); recorder.setMaxDuration(60000); recorder.setOnInfoListener((r, what, extra) -> { if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED) finishRecording(); });
            recorder.prepare(); recorder.start(); record.setText("■"); note("Запись… Нажмите ■, чтобы завершить");
        } catch (Exception e) { if (recorder != null) recorder.release(); recorder = null; if (recording != null) recording.delete(); recording = null; error("Не удалось начать запись. Проверьте микрофон."); }
    }
    private void discardRecording() {
        if (recorder != null) { try { recorder.stop(); } catch (RuntimeException ignored) {} recorder.release(); recorder = null; }
        if (recording != null) { recording.delete(); recording = null; }
    }
    private void finishRecording() {
        if (recorder == null) return;
        try { recorder.stop(); } catch (RuntimeException e) { recorder.release(); recorder = null; if (recording != null) recording.delete(); recording = null; record.setText("🎙"); note("Запись слишком короткая"); return; }
        recorder.release(); recorder = null; record.setText("🎙"); note("Распознаю речь на компьютере…");
        File file = recording; recording = null;
        final EditText destination = composer;
        background(() -> {
            try {
                byte[] audio = Files.readAllBytes(file.toPath()); if (audio.length > 10 * 1024 * 1024) throw new Exception("Запись слишком длинная");
                String boundary = "wiley" + UUID.randomUUID().toString().replace("-", "");
                ByteArrayOutputStream body = new ByteArrayOutputStream();
                body.write(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n").getBytes(StandardCharsets.UTF_8));
                body.write(audio); body.write(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
                JSONObject result = new JSONObject(new String(request(profile, "/api/voice/transcribe", "POST", body.toByteArray(), "multipart/form-data; boundary=" + boundary), StandardCharsets.UTF_8));
                String recognized = result.optString("text");
                onUi(() -> { if (localMode || composer != destination) return; composer.setText(recognized); composer.setSelection(composer.length()); note(recognized.isEmpty() ? "Речь не распознана" : "Проверьте текст и отправьте сообщение"); });
            } catch (Exception e) { onUi(() -> note(e.getMessage())); }
            finally { file.delete(); }
        });
    }
    private void speak(String value) {
        try {
            byte[] audio = jsonRequest("/voice/synthesize", "POST", new JSONObject().put("text", value));
            File file = File.createTempFile("wiley-answer-", ".audio", getCacheDir()); Files.write(file.toPath(), audio);
            onUi(() -> {
                releasePlayer(); playback = file;
                try { player = new MediaPlayer(); player.setDataSource(file.getAbsolutePath()); player.setOnCompletionListener(p -> releasePlayer()); player.setOnPreparedListener(MediaPlayer::start); player.prepareAsync(); }
                catch (Exception e) { releasePlayer(); note("Не удалось воспроизвести ответ"); }
            });
        } catch (Exception e) { onUi(() -> note("Не удалось озвучить ответ: " + e.getMessage())); }
    }
    private void releasePlayer() { if (player != null) { player.release(); player = null; } if (playback != null) { playback.delete(); playback = null; } }

    private void showItems(boolean tasks) {
        if (localMode || profile == null) { note("Задачи и заметки доступны в режиме ПК"); return; }
        if (recorder != null) { note("Сначала завершите запись"); return; }
        final LinearLayout expected = messages;
        note("Загружаю…");
        background(() -> {
            try {
                ensureConversation();
                String endpoint = tasks ? "/tasks" : "/notes";
                JSONArray list = new JSONArray(new String(jsonRequest(endpoint + "?conversation_id=" + query(conversation), "GET", null), StandardCharsets.UTF_8));
                List<String> lines = new ArrayList<>(); lines.add(tasks ? "+ Новая задача" : "+ Новая заметка");
                for (int i = 0; i < list.length(); i++) { JSONObject item = list.getJSONObject(i); lines.add((tasks && taskDone(item) ? "✓ " : "") + item.optString("title", "Без названия")); }
                onUi(() -> { if (localMode || messages != expected) return; ui.dialog().setTitle(tasks ? "Задачи" : "Заметки").setItems(lines.toArray(new String[0]), (dialog, which) -> {
                    if (which == 0) createItem(tasks); else {
                        JSONObject item = list.optJSONObject(which - 1); if (item != null) itemDetails(tasks, item);
                    }
                }).setNegativeButton("Закрыть", null).show(); });
                onUi(() -> note("Подключена к компьютеру"));
            } catch (Exception e) { onUi(() -> note(e.getMessage())); }
        });
    }
    private static boolean taskDone(JSONObject item) { return item.optBoolean("done", false) || item.optInt("done", 0) != 0; }
    private void itemDetails(boolean tasks, JSONObject item) {
        AlertDialog.Builder dialog = ui.dialog().setTitle(item.optString("title"))
                .setMessage(tasks ? (taskDone(item) ? "Выполнена" : "Не выполнена") : item.optString("content"))
                .setPositiveButton("Закрыть", null)
                .setNegativeButton("Удалить", (d, w) -> ui.dialog().setMessage("Удалить эту запись?").setNegativeButton("Отмена", null).setPositiveButton("Удалить", (confirm, choice) -> background(() -> {
                    try { jsonRequest((tasks ? "/tasks/" : "/notes/") + item.getString("id") + "?conversation_id=" + query(conversation), "DELETE", null); onUi(() -> note("Запись удалена")); }
                    catch (Exception e) { error(e.getMessage()); }
                })).show());
        if (tasks) dialog.setNeutralButton(taskDone(item) ? "Вернуть в работу" : "Выполнено", (d, w) -> background(() -> {
            try {
                JSONObject body = new JSONObject().put("title", item.getString("title")).put("kind", item.optString("kind", "todo"))
                        .put("due", item.isNull("due") ? JSONObject.NULL : item.opt("due")).put("done", !taskDone(item));
                if (!item.isNull("recurrence")) {
                    Object recurrence = item.opt("recurrence");
                    body.put("recurrence", recurrence instanceof String ? new JSONObject((String) recurrence) : recurrence);
                }
                jsonRequest("/tasks/" + item.getString("id") + "?conversation_id=" + query(conversation), "PUT", body);
                onUi(() -> note("Задача обновлена"));
            } catch (Exception e) { error(e.getMessage()); }
        }));
        dialog.show();
    }
    private void createItem(boolean tasks) {
        LinearLayout form = vertical(); padded(form, 8); EditText name = field(tasks ? "Название задачи" : "Название заметки"); form.addView(name);
        EditText content = field("Текст заметки"); if (!tasks) { content.setMinLines(3); form.addView(content); }
        ui.dialog().setTitle(tasks ? "Новая задача" : "Новая заметка").setView(form).setNegativeButton("Отмена", null).setPositiveButton("Создать", (d, w) -> {
            String titleValue = name.getText().toString(), contentValue = content.getText().toString();
            background(() -> {
            try {
                JSONObject body = new JSONObject().put("title", titleValue).put(tasks ? "kind" : "content", tasks ? "todo" : contentValue);
                jsonRequest((tasks ? "/tasks" : "/notes") + "?conversation_id=" + query(conversation), "POST", body);
                onUi(() -> note(tasks ? "Задача создана" : "Заметка создана"));
            } catch (Exception e) { error(e.getMessage()); }
            });
        }).show();
    }
}
