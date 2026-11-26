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
    private static final int SPEECH_IMPORT = 72;
    private static final int LLM_IMPORT = 73;
    private static final int GIGAAM_IMPORT = 74;
    private static final int GATEWAY_ATTACHMENT = 76;
    private static final int DIAGNOSTIC_EXPORT = 77;
    private static final int FEEDBACK_EXPORT = 201;
    private byte[] pendingFeedback;
    private String pendingDiagnosticExport;
    private final ExecutorService io = Executors.newCachedThreadPool();
    private final AtomicBoolean chatting = new AtomicBoolean(false);
    private final AtomicBoolean pinging = new AtomicBoolean(false);
    private final Handler pingHandler = new Handler(Looper.getMainLooper());
    private final Runnable pingLoop = new Runnable() { public void run() { if (destroyed || localMode || !page.equals("chat")) return; ping(); pingHandler.postDelayed(this, 15000); } };
    private volatile JSONObject profile;
    private volatile String conversation = "";
    private String requestId = "", lastAnswer = "";
    private boolean readAloud, phoneTarget; private long diagnosticRequestStart;
    private boolean localMode = true, localReady, restoreLocalDraft = true;
    private String pendingProviderTarget; private BrainProvider.Kind providerBeforeSettings;
    private boolean voskChecked, gigaChecked, llmChecked;
    private ChatReadiness.State pcHealth = ChatReadiness.State.UNKNOWN;
    private LinearLayout emptyChat;
    private volatile boolean destroyed;
    private String page = "chat", pcDraft = "", localTitle = "Новый чат";
    private SettingsRepository settings;
    private final PcGateway gateway = new PcGateway();
    private LocalChatController localChats;
    private MobileUi ui;
    private SpeechModelManager speechModels;
    private GigaAmModelManager asrModels;
    private GigaAmSpeechEngine gigaAmSpeech;
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
    private final java.util.ArrayDeque<String> screenTrail = new java.util.ArrayDeque<>();
    private AppCatalog appCatalog;
    private AppCatalogPanel appPanel;
    private boolean resumed, manualWakeSuspended;
    private RuntimeAccess runtimeAccess;
    private FirstRunSetup firstRun;
    private Runnable setupRefresh = () -> {};
    private TextView setupTrialStatus;
    private final Handler draftHandler = new Handler(Looper.getMainLooper());
    private final Runnable saveDraftLater = this::saveDraft;
    private LinearLayout root, messages;
    private ScrollView scroll;
    private TextView status, title, streaming, network;
    private EditText composer;
    private String pendingGuideExample;
    private PermissionPanel permissionPanel;
    private Button send, record, stop;
    private Button modeSwitch;
    private NeonVoiceView headerLogo; private boolean logoCancelled, logoTerminal;
    private MediaRecorder recorder;
    private MediaPlayer player;
    private File recording, playback;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        settings = new SettingsRepository(this);
        runtimeAccess = new RuntimeAccess(this);
        firstRun = new FirstRunSetup(this);
        if (ReleaseUpdates.configured()) {
            var application = getApplicationContext();
            new Handler(Looper.getMainLooper()).postDelayed(() -> {
                UpdateCheckJob.schedule(application);
                ReleaseUpdates.run(() -> ReleaseUpdates.check(application, false));
            }, 15000);
        }
        ui = new MobileUi(this, settings.theme());
        offlineSpeech = new OfflineSpeechEngine(this); systemSpeech = new SystemSpeechEngine(this);
        gigaAmSpeech = new GigaAmSpeechEngine(this, GigaAmRuntime.get(this));
        localVoice = new LocalVoice(this, settings.preferences, this::error);
        localLlm = new LocalLlm(this); cloudChat=new CloudChat(this);gatewayChat=new GatewayClient(this);
        llmModels = new LlmModels(this, () -> { llmChecked=true; updateEmptyChat(); if (page.equals("llm") && llmPanel != null) llmPanel.refresh(); if (page.equals("chat") && localMode && modeSwitch != null) modeSwitch.setText(headerSourceLabel()); if (page.equals("setup")) setupRefresh.run(); });
        speechModels = new SpeechModelManager(this, () -> {
            voskChecked=true; updateEmptyChat();
            if (page.equals("speech") && speechPanel != null) speechPanel.refresh();
            if (page.equals("setup")) refreshSetupAndPermissions();
        });
        asrModels = new GigaAmModelManager(this, () -> { gigaChecked=true; updateEmptyChat(); if (page.equals("speech") && speechPanel != null) speechPanel.refresh(); if (page.equals("setup")) setupRefresh.run(); });
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
                messages.removeAllViews(); emptyChat=null;
                if (hasOlder) messages.addView(button("Показать предыдущие сообщения", () -> { saveDraft(); localChats.loadMore(); }));
                if (list.isEmpty()) welcome();
                for (LocalChatRepository.Message item : list) addMessage(item.role(), item.content());
                title.setText(chatTitle);
                if (restoreLocalDraft) { restoreLocalDraft = false; restoreComposer(draft); }
                note("");
            }
            public void ready(boolean ready) { localReady = ready; if (localMode) { if (send != null) send.setEnabled(ready && !recognitionBusy() && !chatting.get()); if (ready && composer != null && !recognitionBusy() && !chatting.get()) composer.setEnabled(true); } }
            public void error(String message) { MainActivity.this.error(message); }
        });
        String profileError = null;
        try { profile = readProfile(); } catch (Exception ignored) { profile = null; profileError = "Не удалось прочитать защищённое подключение. Создайте новый код на ПК и выполните сопряжение. Сохранённые данные подключения не удалены."; }
        localMode = !ChatHeaderPolicy.restorePc(settings.preferences.getBoolean("chat_source_pc",false),profile!=null);
        Uri incoming = getIntent() != null ? getIntent().getData() : null;
        if (MediaPanel.SETTINGS.equals(getIntent().getAction())) showSection("media");
        else if (ReleaseUpdates.OPEN.equals(getIntent().getAction())) showSection("about");
        else if (HandsFreeService.SETTINGS.equals(getIntent().getAction()) || Intent.ACTION_ASSIST.equals(getIntent().getAction())) showSection("assistant");
        else if (incoming != null) showPair(incoming.toString());
        else if (firstRun.shouldOpen(this)) showSection("setup");
        else showChat();
        if (profileError != null) error(profileError);
        if (!page.equals("setup")) showDiagnosticNotice();
    }

    private void showDiagnosticNotice() {
        if (!getSharedPreferences("wiley-diagnostics",MODE_PRIVATE).getBoolean("notice_shown",false)) {
            getSharedPreferences("wiley-diagnostics",MODE_PRIVATE).edit().putBoolean("notice_shown",true).apply();
            ui.dialog().setTitle("Локальная диагностика").setMessage("WileyAI сохраняет технические события на устройстве до 7 дней, не записывая разговоры, аудио и секреты. Журнал никуда не отправляется автоматически. Его можно отключить или очистить в настройках.")
                .setPositiveButton("Понятно",null).setNegativeButton("Отключить",(d,w)->DiagnosticLog.stop()).show();
        }
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (MediaPanel.SETTINGS.equals(intent.getAction())) { saveDraft(); showSection("media"); return; }
        if (ReleaseUpdates.OPEN.equals(intent.getAction())) { if (canNavigate()) openSection("about"); return; }
        if (HandsFreeService.SETTINGS.equals(intent.getAction()) || Intent.ACTION_ASSIST.equals(intent.getAction())) { saveDraft(); showSection("assistant"); return; }
        if (chatting.get() || recognitionBusy()) { error("Сначала завершите текущий ответ или запись и откройте ссылку подключения ещё раз."); return; }
        saveDraft();
        discardRecording();
        if (intent.getData() != null) showPair(intent.getData().toString());
    }

    @Override protected void onDestroy() {
        releaseManualWake();
        destroyed = true;
        if(brain!=null)brain.close();if(brainPanel!=null)brainPanel.close();
        if (mediaPanel != null) mediaPanel.close(); if (assistantPanel != null) assistantPanel.close();
        localLlm.close(); cloudChat.close();gatewayChat.close();if(gatewayPanel!=null)gatewayPanel.close();llmModels.close();
        if (voicePanel != null) voicePanel.close(); offlineSpeech.close(); systemSpeech.close(); gigaAmSpeech.close(); speechModels.close(); asrModels.close(); localVoice.close(); appCatalog.close();
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
    @Override protected void onResume() { super.onResume(); resumed = true;if(ui!=null)ui.pauseArt(false);DiagnosticLog.event(DiagnosticJournal.Event.APP_OPEN,0); refreshSetupAndPermissions();if(brainPanel!=null)brainPanel.refreshScreenStatus(); configureHeaderLogo(); updateEmptyChat();if(gatewayPanel!=null)gatewayPanel.refresh();if(modeSwitch!=null&&localMode)modeSwitch.setText(headerSourceLabel());pingHandler.removeCallbacks(pingLoop); pingHandler.post(pingLoop); }

    private void refreshSetupAndPermissions() {
        if (assistantPanel != null) assistantPanel.refresh();
        if (permissionPanel != null) permissionPanel.refresh();
        if (page.equals("setup")) setupRefresh.run();
    }
    @Override protected void onPause() { if(ui!=null)ui.pauseArt(true);DiagnosticLog.event(DiagnosticJournal.Event.APP_BACKGROUND,0);resumed = false;if(headerLogo!=null)headerLogo.paused(true);if(brain!=null)brain.pauseLocal(); offlineSpeech.cancel(); systemSpeech.cancel(); gigaAmSpeech.cancel(); localLlm.cancel(); cloudChat.cancel();localVoice.stop(); saveDraft(); discardRecording(); if (record != null) setRecordIcon(false); pingHandler.removeCallbacks(pingLoop); super.onPause(); }

    @Override protected void onSaveInstanceState(Bundle state) { saveDraft(); super.onSaveInstanceState(state); }
    private void saveDraft() {
        draftHandler.removeCallbacks(saveDraftLater);
        if (!page.equals("chat") || composer == null) return;
        if (localMode) { if (!restoreLocalDraft) localChats.saveDraft(composer.getText().toString()); }
        else { pcDraft = composer.getText().toString(); settings.preferences.edit().putString("pc_draft", pcDraft).apply(); }
    }
    private boolean recognitionBusy() { return offlineSpeech.busy() || systemSpeech.busy() || gigaAmSpeech.busy(); }
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
    private void layout() {permissionPanel=null;if(brainPanel!=null){brainPanel.close();brainPanel=null;}if(gatewayPanel!=null){gatewayPanel.close();gatewayPanel=null;} if (mediaPanel != null) { mediaPanel.close(); mediaPanel = null; } if (assistantPanel != null) { assistantPanel.close(); assistantPanel = null; } modeSwitch = null; headerLogo=null; if (!page.equals("llm")) llmPanel = null; pingHandler.removeCallbacks(pingLoop); if (!page.equals("apps")) appPanel = null; if (!page.equals("speech")) speechPanel = null; if (voicePanel != null) { voicePanel.close(); voicePanel = null; } network = null; status = null; composer = null; messages = null; emptyChat = null; send = null; root = ui.root(); }
    private void note(String message) { if (status != null) { status.setText(message); status.setVisibility(message == null || message.isEmpty() ? View.GONE : View.VISIBLE); } }
    private void error(String message) { DiagnosticLog.event(DiagnosticJournal.Event.UI_ERROR,0);onUi(() -> { if (!isDestroyed() && !isFinishing()) ui.dialog().setTitle("WileyAI").setMessage(message).setPositiveButton("Понятно", null).show(); }); }
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

    private NeonVoiceView makeHeaderLogo() {
        NeonVoiceView logo=new NeonVoiceView(this,true);logo.setContentDescription(null);
        var prefs=settings.preferences;logo.configure(prefs.getInt("neon_intensity",2),prefs.getBoolean("neon_logo",true),prefs.getBoolean("neon_reduce",false));
        logo.paused(!resumed);return logo;
    }
    private void configureHeaderLogo(){if(headerLogo!=null){var p=settings.preferences;headerLogo.configure(p.getInt("neon_intensity",2),p.getBoolean("neon_logo",true),p.getBoolean("neon_reduce",false));headerLogo.paused(!resumed);}}
    boolean artModelBusy(){return chatting.get() || (localLlm!=null&&localLlm.busy()) || HandsFreeService.answering();}
    private void logoState(NeonVoiceView.Mode state){if(headerLogo!=null)headerLogo.state(state);}
    private void logoStart(){diagnosticRequestStart=android.os.SystemClock.elapsedRealtime();DiagnosticLog.event(DiagnosticJournal.Event.MODEL_BEGIN,0);logoCancelled=false;logoTerminal=false;logoState(NeonVoiceView.Mode.PROCESSING);}
    private void logoEnd(boolean success){if(logoCancelled){logoState(NeonVoiceView.Mode.IDLE);return;}DiagnosticLog.event(success?DiagnosticJournal.Event.MODEL_DONE:DiagnosticJournal.Event.MODEL_ERROR,diagnosticRequestStart==0?0:android.os.SystemClock.elapsedRealtime()-diagnosticRequestStart);logoTerminal=true;logoState(success?NeonVoiceView.Mode.SUCCESS:NeonVoiceView.Mode.ERROR);}
    private void showChat() {
        if (page.equals("setup")) ui = new MobileUi(this, settings.theme());
        if(pendingProviderTarget!=null){BrainProvider.Kind current=new ModelManager(this).selected();if(providerBeforeSettings!=null&&ChatHeaderPolicy.activateAfterSettings(pendingProviderTarget,providerBeforeSettings.name(),current.name()))localMode=true;pendingProviderTarget=null;providerBeforeSettings=null;}
        settings.preferences.edit().putBoolean("chat_source_pc",!localMode).apply();
        long diagnosticScreenBegan=android.os.SystemClock.elapsedRealtime();DiagnosticLog.event(DiagnosticJournal.Event.SCREEN_CHAT,0);screenTrail.clear(); page = "chat"; restoreLocalDraft = true;
        layout();
        LinearLayout header = row();header.setPadding(dp(12),dp(5),dp(12),dp(3));header.setGravity(Gravity.CENTER_VERTICAL);
        headerLogo=makeHeaderLogo();header.addView(headerLogo,new LinearLayout.LayoutParams(dp(34),dp(34)));
        Button mode=button(headerSourceLabel(),()->showSourcePopup(modeSwitch));modeSwitch=mode;ui.headerControl(mode);mode.setMinWidth(dp(112));mode.setMinimumWidth(dp(112));mode.setSingleLine(true);mode.setEllipsize(android.text.TextUtils.TruncateAt.END);mode.setContentDescription("Источник ответа");
        android.widget.FrameLayout sourceSlot=new android.widget.FrameLayout(this);sourceSlot.addView(mode,new android.widget.FrameLayout.LayoutParams(-2,dp(48),Gravity.START|Gravity.CENTER_VERTICAL));
        LinearLayout.LayoutParams modeParams=new LinearLayout.LayoutParams(0,dp(48),1);modeParams.setMargins(dp(8),0,dp(6),0);header.addView(sourceSlot,modeParams);
        boolean compactHistory=getResources().getConfiguration().screenWidthDp<375 || (getResources().getConfiguration().fontScale>1.2f && getResources().getConfiguration().screenWidthDp<430);
        Button history=button(compactHistory?"История":"История чатов",()->{});history.setContentDescription("История чатов");history.setTextSize(compactHistory?12:13);history.setSingleLine(true);history.setEllipsize(android.text.TextUtils.TruncateAt.END);history.setMinWidth(0);history.setMinimumWidth(0);ui.headerControl(history);
        android.graphics.drawable.Drawable historyIcon=getDrawable(R.drawable.nav_chat).mutate();historyIcon.setTint(ui.theme.accentText);historyIcon.setBounds(0,0,dp(18),dp(18));history.setCompoundDrawables(historyIcon,null,null,null);history.setCompoundDrawablePadding(dp(4));history.setOnClickListener(v->showHistoryPopup(history));
        header.addView(history,new LinearLayout.LayoutParams(dp(compactHistory?124:165),dp(48)));root.addView(header);
        title=text(localMode?localTitle:"История ПК",13,ui.theme.secondary);title.setPadding(dp(16),0,dp(16),dp(3));title.setSingleLine(true);title.setEllipsize(android.text.TextUtils.TruncateAt.END);root.addView(title);
        network = text(localMode ? "" : "Проверка связи…", 12, ui.theme.accentText);
        if (!localMode) { padded(network, 2); root.addView(network); }
        status = text("", 12, ui.theme.muted); padded(status, 0); status.setMaxLines(2); status.setVisibility(View.GONE); root.addView(status);
        if (!localMode) {
            LinearLayout tools = row(); padded(tools, 0);
            tools.addView(button("Задачи ПК", () -> showItems(true)), new LinearLayout.LayoutParams(0, dp(48), 1));
            tools.addView(button("Заметки ПК", () -> showItems(false)), new LinearLayout.LayoutParams(0, dp(48), 1));
            Button target = button(phoneTarget ? "Телефон" : "ПК", () -> {});
            target.setOnClickListener(v -> { phoneTarget = !phoneTarget; target.setText(phoneTarget ? "Телефон" : "ПК"); note(phoneTarget ? "Команды выполняются на телефоне" : "Команды выполняются на компьютере"); });
            tools.addView(target, new LinearLayout.LayoutParams(dp(82), dp(48))); root.addView(tools);
        }
        scroll = new ScrollView(this); scroll.setFillViewport(true); messages = vertical(); messages.setPadding(dp(12), dp(6), dp(12), dp(6)); scroll.addView(messages);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        stop = button("Остановить ответ", this::stopChat); stop.setVisibility(View.GONE); root.addView(stop);
        if(localMode&&GatewayClient.enabled(this)){
            Button attach=button("Прикрепить файл",this::pickGatewayAttachment);
            try{JSONObject selected=settings.readGateway();if(selected!=null){JSONArray pending=selected.optJSONArray("pending_attachments");if(pending!=null&&pending.length()>0)attach.setText("Файлов: "+pending.length()+" · добавить");attach.setEnabled(GatewayClient.supports(selected,"vision")||GatewayClient.supports(selected,"file_upload"));}}catch(Exception ignored){attach.setEnabled(false);}
            root.addView(attach);
        }
        LinearLayout bar = row(); bar.setGravity(Gravity.CENTER_VERTICAL);bar.setPadding(dp(14),dp(5),dp(14),dp(7));bar.setClipChildren(false);
        composer = field(localMode ? "Например: открой Telegram" : "Сообщение Уайли…"); composer.setMaxLines(4); composer.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        composer.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int count) { draftHandler.removeCallbacks(saveDraftLater); draftHandler.postDelayed(saveDraftLater, 400); }
            public void afterTextChanged(android.text.Editable text) {}
        });
        bar.addView(composer, new LinearLayout.LayoutParams(0, -2, 1));
        ui.focusField(composer);
        record = ui.roundControl("", this::toggleRecording); ui.controlIcon(record,R.drawable.ui_mic); record.setContentDescription("Начать или завершить запись голоса"); LinearLayout.LayoutParams micParams=new LinearLayout.LayoutParams(dp(48),dp(48));micParams.setMargins(dp(7),0,0,0);bar.addView(record,micParams);
        send = ui.roundControl("", this::send); ui.controlIcon(send,R.drawable.ui_send); send.setContentDescription("Отправить сообщение"); send.setTextColor(ui.theme.accentText); LinearLayout.LayoutParams sendParams=new LinearLayout.LayoutParams(dp(48),dp(48));sendParams.setMargins(dp(7),0,0,0);bar.addView(send,sendParams); root.addView(bar);
        navigation("chat");trackDiagnosticScreenDraw(diagnosticScreenBegan);
        if (localMode) { composer.setEnabled(false); send.setEnabled(false); localChats.load(); }
        else { pcHealth=profile==null?ChatReadiness.State.SETUP_REQUIRED:ChatReadiness.State.CHECKING; restoreComposer(settings.preferences.getString("pc_draft", "")); if (!conversation.isEmpty()) background(this::loadMessages); pingHandler.post(pingLoop); }
    }
    private ChatReadiness.Facts chatFacts() {
        ChatReadiness.State vosk = ChatReadiness.asset(voskChecked, speechModels.busy(), speechModels.active()!=null, voskChecked && speechModels.active()==null && speechModels.removable());
        ChatReadiness.State giga = ChatReadiness.asset(gigaChecked, asrModels.busy(), asrModels.active()!=null, gigaChecked && asrModels.active()==null && asrModels.removable());
        ChatReadiness.State model = ChatReadiness.asset(llmChecked, llmModels.busy(), llmModels.active()!=null, llmChecked && llmModels.status().startsWith("Не удалось"));
        int engine=settings.preferences.getInt("asr_engine",0);
        ChatReadiness.State system = android.speech.SpeechRecognizer.isRecognitionAvailable(this) ? ChatReadiness.State.UNKNOWN : ChatReadiness.State.UNAVAILABLE;
        if(engine==2 && (Build.VERSION.SDK_INT<31 || !android.speech.SpeechRecognizer.isOnDeviceRecognitionAvailable(this))) system=ChatReadiness.State.UNAVAILABLE;
        ChatReadiness.State speech=ChatReadiness.selectedSpeech(engine,vosk,giga,system);
        ChatReadiness.State mic=chatFactsMicPermission() ? ChatReadiness.State.UNKNOWN : ChatReadiness.State.SETUP_REQUIRED;
        ChatReadiness.State manual=mic==ChatReadiness.State.SETUP_REQUIRED ? mic : ChatReadiness.manualVoice(localMode || phoneTarget,true,speech,pcHealth);
        BrainProvider.Kind selected=new ModelManager(this).selected();
        ChatReadiness.Source source=!localMode ? ChatReadiness.Source.PC : selected==BrainProvider.Kind.REMOTE_GATEWAY ? ChatReadiness.Source.GATEWAY : selected==BrainProvider.Kind.ACCOUNT_OAUTH ? ChatReadiness.Source.ACCOUNT : selected==BrainProvider.Kind.LOCAL ? ChatReadiness.Source.LOCAL : ChatReadiness.Source.CLOUD;
        ChatReadiness.State pc=profile==null ? ChatReadiness.State.SETUP_REQUIRED : pcHealth;
        return new ChatReadiness.Facts(manual,vosk,speech,model,source,ChatReadiness.source(source,model,pc,ChatReadiness.State.UNKNOWN),pc);
    }
    private boolean chatFactsMicPermission(){return checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED;}
    private void welcome() {
        emptyChat=vertical(); emptyChat.setPadding(dp(4),dp(12),dp(4),dp(8)); messages.addView(emptyChat); updateEmptyChat();
    }
    private void updateEmptyChat() {
        if(emptyChat==null || !page.equals("chat") || !localMode || speechModels==null || asrModels==null || llmModels==null)return;
        ChatReadiness.Facts facts=chatFacts(); emptyChat.removeAllViews();
        TextView heading=text("Чем помочь?",20,ui.theme.text); ui.typography(heading,600); emptyChat.addView(heading);
        ChatReadiness.Hint hint=ChatReadiness.hint(facts);
        if(hint==ChatReadiness.Hint.SPEECH){
            boolean microphoneMissing=!chatFactsMicPermission();
            emptyChat.addView(text(microphoneMissing ? "Разрешите микрофон для голосового ввода." : "Распознавание речи не настроено.",14,ui.theme.secondary));
            emptyChat.addView(button(microphoneMissing ? "Настройки микрофона" : "Настроить распознавание", microphoneMissing ? () -> startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:"+getPackageName()))) : ()->openSection("speech")));
        } else if(hint==ChatReadiness.Hint.SPEECH_CHECK){
            emptyChat.addView(text("Распознавание речи временно недоступно. Проверьте настройки.",14,ui.theme.secondary));
            emptyChat.addView(button("Проверить распознавание",()->openSection("speech")));
        } else if(hint==ChatReadiness.Hint.MODEL || hint==ChatReadiness.Hint.MODEL_CHECK){
            emptyChat.addView(text(hint==ChatReadiness.Hint.MODEL ? "Для свободного разговора настройте модель." : "Не удалось проверить модель. Откройте настройки.",14,ui.theme.secondary));
            emptyChat.addView(button("Выбрать модель",()->openSection("llm")));
        } else emptyChat.addView(text("Напишите сообщение или скажите команду.",14,ui.theme.secondary));
    }
    private void tryGuideExample(String example) {
        if(!canNavigate())return;
        pendingGuideExample=example;
        showChat();
    }
    private void restoreComposer(String draft) {
        String example=pendingGuideExample;
        pendingGuideExample=null;
        EditText target=composer;
        target.setText(example!=null&&draft.isBlank()?example:draft);
        target.setSelection(target.length());
        if(example!=null&&!draft.isBlank()){
            ui.dialog().setTitle("Заменить черновик примером?")
                .setNegativeButton("Оставить черновик",null)
                .setPositiveButton("Вставить пример",(d,w)->{
                    if(composer!=target)return;
                    target.setText(example);
                    target.setSelection(target.length());
                }).show();
        }
    }
    private void navigation(String current) {
        LinearLayout outer=row();outer.setPadding(dp(12),dp(2),dp(12),dp(2));
        LinearLayout nav=row();nav.setPadding(dp(6),dp(5),dp(6),dp(5));nav.setBackground(ui.panel(ui.theme.low,20));
        String[] names={"Чат","Моё","Настройки"};
        String[] displayNames=getResources().getConfiguration().screenWidthDp<360?new String[]{"Чат","Моё","Опции"}:names;
        int[] icons={R.drawable.nav_chat,R.drawable.nav_features,R.drawable.nav_settings};
        String[] pages={"chat","personal","settings"};
        for(int i=0;i<names.length;i++){
            final String target=pages[i];Button item=button(displayNames[i],()->{if(!canNavigate())return;screenTrail.clear();if(target.equals("chat"))showChat();else showSection(target);});
            item.setPadding(dp(2),dp(4),dp(2),dp(4));item.setTextSize(13);item.setSingleLine(false);item.setMaxLines(2);item.setMinHeight(dp(52));item.setMinWidth(0);item.setMinimumWidth(0);
            android.graphics.drawable.Drawable glyph=getDrawable(icons[i]).mutate();glyph.setTint(current.equals(target)?ui.theme.accentText:ui.theme.secondary);glyph.setBounds(0,0,dp(22),dp(22));
            item.setCompoundDrawables(null,glyph,null,null);item.setCompoundDrawablePadding(dp(2));item.setSelected(current.equals(target));item.setContentDescription(names[i]);ui.navigationItem(item,current.equals(target));
            LinearLayout.LayoutParams navParams=new LinearLayout.LayoutParams(0,-2,1);navParams.setMargins(dp(3),0,dp(3),0);nav.addView(item,navParams);
        }
        outer.addView(nav,new LinearLayout.LayoutParams(-1,-2));root.addView(outer);
    }
    private String headerSourceLabel(){
        if(!localMode)return "ПК ▾";
        return switch(new ModelManager(this).selected()){
            case REMOTE_GATEWAY -> "Gateway ▾";
            case ACCOUNT_OAUTH -> "ChatGPT ▾";
            case DIRECT_CLOUD,OFFICIAL_API -> "Облако ▾";
            default -> "Телефон ▾";
        };
    }
    private void showSourcePopup(View anchor){
        if(anchor==null||!canNavigate())return;
        ChatHeaderPopup menu=new ChatHeaderPopup(this,ui,anchor);BrainProvider.Kind kind=new ModelManager(this).selected();
        boolean localSelected=localMode&&kind==BrainProvider.Kind.LOCAL;
        menu.label("Источник ответа");
        menu.row("Телефон",(llmModels.active()!=null?"Qwen3 0.6B":"Модель не установлена")+(localSelected?" · выбран":""),R.drawable.nav_features,localSelected,()->{
            if(!canNavigate())return;new ModelManager(this).local();localMode=true;showChat();
        });
        String pcStatus=profile==null?"Подключение не настроено":pcHealth==ChatReadiness.State.READY?"Подключён":pcHealth==ChatReadiness.State.UNAVAILABLE?"Недоступен":"Подключение сохранено";
        menu.row("ПК",pcStatus+(!localMode?" · выбран":""),R.drawable.ui_screen,!localMode,()->{
            if(!canNavigate())return;if(profile==null){showPair("");return;}localMode=false;showChat();
        });
        boolean cloud=localMode&&(kind==BrainProvider.Kind.DIRECT_CLOUD||kind==BrainProvider.Kind.OFFICIAL_API);
        boolean gatewaySelected=localMode&&kind==BrainProvider.Kind.REMOTE_GATEWAY;
        boolean account=localMode&&kind==BrainProvider.Kind.ACCOUNT_OAUTH;
        menu.row("Облако",cloud?"Выбрано · настройки модели":"Выбрать и настроить модель",R.drawable.nav_chat,cloud,()->selectProvider("cloud","cloud"));
        menu.row("Gateway",gatewaySelected?"Выбран · настройки":"Выбрать или настроить",R.drawable.nav_features,gatewaySelected,()->selectProvider("gateway","connections"));
        menu.row("ChatGPT",account?"Выбран · настройки аккаунта":"Вход и выбор модели",R.drawable.nav_chat,account,()->selectProvider("account","neural"));
        menu.show();
    }
    private boolean providerMatches(String target,BrainProvider.Kind kind){
        return ChatHeaderPolicy.matches(target,kind.name());
    }
    private void selectProvider(String target,String section){
        if(!canNavigate())return;BrainProvider.Kind current=new ModelManager(this).selected();
        if(!localMode&&providerMatches(target,current)){localMode=true;showChat();return;}
        pendingProviderTarget=target;providerBeforeSettings=current;screenTrail.addLast(page);showSection(section);
    }
    private void showHistoryPopup(View anchor){
        if(anchor==null||!canNavigate())return;
        final boolean phone=localMode;final LinearLayout expected=messages;
        final ChatHeaderPopup menu=new ChatHeaderPopup(this,ui,anchor);
        if(phone){
            fillPhoneHistory(menu,java.util.Collections.emptyList(),true);menu.show();
            localChats.list(chats->{if(!menu.showing()||!localMode||messages!=expected||!page.equals("chat"))return;fillPhoneHistory(menu,chats,false);menu.resize();});
            return;
        }
        fillPcHistory(menu,null,true);menu.show();
        if(profile==null){fillPcHistory(menu,null,false);menu.resize();return;}
        final JSONObject expectedProfile=profile;
        background(()->{
            try{
                JSONArray chats=new JSONArray(new String(jsonRequest("/conversations","GET",null),StandardCharsets.UTF_8));
                onUi(()->{if(!menu.showing()||localMode||messages!=expected||profile!=expectedProfile||!page.equals("chat"))return;fillPcHistory(menu,chats,false);menu.resize();});
            }catch(Exception e){onUi(()->{if(menu.showing()&&!localMode&&messages==expected){fillPcHistory(menu,null,false);menu.resize();}});}
        });
    }
    private void fillPhoneHistory(ChatHeaderPopup menu,java.util.List<LocalChatRepository.Chat> chats,boolean loading){
        menu.clear();menu.label("История телефона · общая для источников");
        menu.row("Начать новый чат","Телефон",R.drawable.nav_chat,false,()->{
            if(!localMode||!canNavigate())return;restoreLocalDraft=true;composer.setEnabled(false);localChats.choose("");
        });

        if(loading)menu.label("Загружаю…");
        else if(chats.isEmpty())menu.label("Нет сохранённых чатов");
        else {
            String selected=settings.preferences.getString("phone_chat","");int limit=Math.min(5,chats.size());
            for(int i=0;i<limit;i++){
                LocalChatRepository.Chat chat=chats.get(i);boolean current=chat.id().equals(selected);
                menu.row(chat.title(),current?"Текущий чат":"Телефон",R.drawable.nav_chat,current,()->{
                    if(!localMode||!canNavigate())return;restoreLocalDraft=true;composer.setEnabled(false);localChats.choose(chat.id());
                });
            }
        }
        menu.row("Вся история","Переименование и удаление",R.drawable.nav_chat,false,this::chooseLocalChat);
    }
    private void fillPcHistory(ChatHeaderPopup menu,JSONArray chats,boolean loading){
        menu.clear();menu.label("История компьютера");
        menu.row("Начать новый чат","ПК",R.drawable.nav_chat,false,()->{
            if(localMode||!canNavigate())return;conversation="";settings.preferences.edit().remove("chat").apply();if(messages!=null)messages.removeAllViews();note("Новый чат ПК");
        });

        if(loading)menu.label("Загружаю…");
        else if(chats==null)menu.label(profile==null?"Компьютер не подключён":"Не удалось загрузить историю");
        else if(chats.length()==0)menu.label("Нет сохранённых чатов");
        else for(int i=0;i<Math.min(5,chats.length());i++){
            JSONObject chat=chats.optJSONObject(i);if(chat==null)continue;String id=chat.optString("id","");if(id.isEmpty())continue;
            boolean current=id.equals(conversation);menu.row(chat.optString("title","Чат"),current?"Текущий чат · ПК":"ПК",R.drawable.nav_chat,current,()->{
                if(localMode||!canNavigate())return;conversation=id;settings.preferences.edit().putString("chat",id).apply();background(this::loadMessages);
            });
        }
        menu.row("Вся история","Чаты компьютера",R.drawable.nav_chat,false,this::chooseChat);
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
        if (page.equals("setup") && firstRun.step() > 0) {
            setupStep(firstRun.step() - 1);
            return;
        }
        if (!screenTrail.isEmpty()) { String previous = screenTrail.removeLast(); if (previous.equals("chat")) showChat(); else showSection(previous); }
        else if (!page.equals("chat")) showChat(); else finish();
    }
    private void showSection(String section) {
        long diagnosticScreenBegan=android.os.SystemClock.elapsedRealtime();DiagnosticLog.event(switch(section){case "guide", "commands" -> DiagnosticJournal.Event.SCREEN_COMMANDS;case "settings" -> DiagnosticJournal.Event.SCREEN_SETTINGS;default -> DiagnosticJournal.Event.SCREEN_OTHER;},0);
        if(page.equals("chat")&&!section.equals("chat")){localLlm.cancel();if(brain!=null)brain.pauseLocal();}
        if (section.equals("setup") || page.equals("setup")) {
            String theme = settings.theme();
            ui = new MobileUi(this, section.equals("setup") && "system".equals(theme) ? "aurora" : theme);
        }
        page = section; setupRefresh = () -> {}; setupTrialStatus = null; layout();
        String heading = switch(section) {
            case "personal" -> "Моё"; case "commands" -> "Проверка команд"; case "speech" -> "Распознавание речи";
            case "neural" -> "Мозг";case "connections" -> "Gateway";case "apps" -> "Любимые приложения"; case "media" -> "Музыка и YouTube"; case "assistant" -> "Голосовой вызов"; case "voice" -> "Озвучка"; case "llm" -> "Локальные модели"; case "cloud" -> "Облачные модели"; case "pc" -> "Устройства и подключения";
            case "profile" -> "Мой профиль"; case "memory" -> "Память WileyAI"; case "communication" -> "Как со мной общаться";
            case "guide" -> "Подсказки и команды"; case "levels" -> "Уровень управления"; case "notes" -> "Заметки и напоминания"; case "phone_notes" -> "Заметки телефона"; case "phone_reminders" -> "Напоминания телефона";
            case "permissions" -> "Разрешения и безопасность"; case "screen" -> "Наблюдение экрана"; case "app_defaults" -> "Приложения по умолчанию";
            case "setup" -> "Настройка WileyAI";
            case "cloud_tools" -> "Инструменты и облако"; case "advanced" -> "Дополнительно"; case "about" -> "О приложении"; default -> "Настройки";
        };
        LinearLayout header = row(); padded(header, 8);
        if (!screenTrail.isEmpty()) { Button back = button("‹", this::handleBack); back.setContentDescription("Назад"); header.addView(back, new LinearLayout.LayoutParams(dp(48), dp(48))); }
        headerLogo=makeHeaderLogo();header.addView(headerLogo,new LinearLayout.LayoutParams(dp(32),dp(32)));
        TextView sectionTitle=text(heading,24,ui.theme.text);sectionTitle.setPadding(dp(8),0,0,0);header.addView(sectionTitle, new LinearLayout.LayoutParams(0, -2, 1)); root.addView(header);
        ScrollView content = new ScrollView(this); LinearLayout cards = vertical(); padded(cards, 8); content.addView(cards);
        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1));
        switch (section) {
            case "media":
                mediaPanel = new MediaPanel(this, ui, appCatalog, () -> resumed && page.equals("media")); mediaPanel.render(cards,()->openSection("app_defaults")); break;
            case "assistant":
                assistantPanel = createAssistantPanel(); assistantPanel.render(cards); break;
            case "setup": renderSetup(cards); break;
            case "llm":
                llmPanel = new LlmPanel(this, ui, llmModels, settings.preferences, () -> localLlm.busy() || (brain!=null&&brain.busy()) || HandsFreeService.answering(), () -> {
                    Intent file = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);
                    try { startActivityForResult(file, LLM_IMPORT); } catch (Exception error) { error("Нет приложения выбора файла"); }
                }, () -> { settings.preferences.edit().putBoolean("gateway_enabled",false).putBoolean("cloud_enabled",false).putBoolean("account_enabled",false).apply();localMode = true; showChat(); }); llmPanel.render(cards); break;
            case "speech": speechPanel = speechPanel(); speechPanel.render(cards); break;
            case "voice":
                voicePanel = new VoicePanel(this, ui, localVoice, settings.preferences, value -> {
                    readAloud = value; settings.preferences.edit().putBoolean("read_aloud", value).apply(); if (!value) { localVoice.stop(); releasePlayer(); }
                }, () -> { localVoice.stop(); releasePlayer(); });
                voicePanel.render(cards); break;
            case "personal":
                ui.link(cards,"Мой профиль","Обращение и предпочтения",()->openSection("profile"),R.drawable.nav_features);
                ui.link(cards,"Память WileyAI","Подтверждённые записи на телефоне",()->openSection("memory"),R.drawable.nav_chat);
                ui.link(cards,"Как со мной общаться","Стиль ответов и инструкции",()->openSection("communication"),R.drawable.nav_chat);
                ui.link(cards,"Любимые приложения","Выбор по умолчанию и голосовые названия",()->openSection("apps"),R.drawable.nav_features);
                ui.link(cards,"Заметки и напоминания","Записи телефона и компьютера",()->openSection("notes"),R.drawable.ui_reminder);
                ui.link(cards,"Подсказки и команды","Примеры для чата",()->openSection("guide"),R.drawable.ui_screen);
                ui.link(cards,"Уровень управления","Доступные возможности телефона",()->openSection("levels"),R.drawable.nav_settings);
                break;
            case "profile": new PersonalPanel(this,ui).profile(cards); break;
            case "memory": new PersonalPanel(this,ui).memory(cards); break;
            case "communication": new PersonalPanel(this,ui).communication(cards); break;
            case "guide":
                ModelManager guideModel=new ModelManager(this);
                boolean chatReady=localMode?guideModel.selected()!=BrainProvider.Kind.LOCAL||llmModels.active()!=null:profile!=null;
                CommandGuide.render(this,ui,cards,chatReady,localMode&&chatReady&&guideModel.toolsAllowed(),this::tryGuideExample,this::openSection);
                break;
            case "levels":
                ui.card(cards,"Базовый","Запуск приложений, громкость, разговор и управление доступными плеерами.");
                ui.link(cards,"Расширенный","Наблюдение за экраном по запросу через Accessibility",()->openSection("screen"));
                ui.card(cards,"Системный · пока недоступен","Интеграция управления через ADB пока не реализована.");
                break;
            case "notes":
                ui.link(cards,"Телефон · заметки","Доступны без интернета",()->openSection("phone_notes"));
                ui.link(cards,"Телефон · задачи и напоминания","Локальные напоминания WileyAI",()->openSection("phone_reminders"));
                ui.link(cards,"Компьютер · заметки",profile==null?"Подключить компьютер":"Открыть записи ПК",()->openPcRecords(false));
                ui.link(cards,"Компьютер · задачи и напоминания",profile==null?"Подключить компьютер":"Открыть задачи ПК",()->openPcRecords(true));
                break;
            case "phone_notes": new NotesPanel(this,ui).render(cards); break;
            case "phone_reminders":
                try(ToolsData data=new ToolsData(this)) {
                    var reminders=data.reminders();
                    if(reminders.isEmpty()) cards.addView(ui.text("Напоминаний пока нет.",14,ui.theme.secondary));
                    for(var reminder:reminders) ui.card(cards,android.text.format.DateFormat.format("dd.MM.yyyy HH:mm",(Long)reminder.get("due")).toString(),reminder.get("text")+(Boolean.TRUE.equals(reminder.get("delivered"))?" · доставлено":" · ожидается"));
                }
                cards.addView(ui.text("Напоминание можно создать командой после подтверждения. Android может задержать уведомление.",14,ui.theme.secondary));
                break;
            case "permissions":
                permissionPanel=new PermissionPanel(this,ui,runtimeAccess);
                permissionPanel.render(cards,()->openSection("screen"),()->{
                    if(brainPanel==null)brainPanel=createBrainPanel();
                    brainPanel.screenApps();
                },()->openSection("cloud_tools"));
                break;
            case "screen":
                brainPanel=createBrainPanel();
                brainPanel.renderScreenSettings(cards);
                break;
            case "cloud_tools":
                brainPanel=createBrainPanel();
                brainPanel.toolPermissions(cards);
                break;
            case "advanced":
                ui.link(cards,"Проверка команд","Ручной запуск и результат",()->openSection("commands"));
                brainPanel=createBrainPanel();
                brainPanel.renderModelExtras(cards);
                break;
            case "commands":
                CommandPanel.render(this,ui,cards,appCatalog,settings.preferences,()->resumed&&page.equals("commands"));
                break;
            case "apps":
                appPanel = new AppCatalogPanel(this, ui, appCatalog, () -> resumed && page.equals("apps"));
                appPanel.render(cards,()->openSection("app_defaults"),()->openSection("media"),()->openSection("permissions")); break;
            case "app_defaults":
                new AppCatalogPanel(this,ui,appCatalog,()->resumed&&page.equals("app_defaults")).renderDefaults(cards);
                break;
            case "cloud":
                new CloudPanel(this,ui).render(cards);
                break;
            case "neural":
                brainPanel=createBrainPanel(); brainPanel.render(cards); break;
            case "connections":
                gatewayPanel=new GatewayPanel(this,ui,gatewayChat,()->openSection("llm"));gatewayPanel.render(cards);break;
            case "pc": renderPc(cards); break;
            case "about": new AboutPanel(this, ui, this::saveFeedback).render(cards); break;
            default:
                ui.link(cards,"Мозг","Локальные, облачные модели и подключения",()->openSection("neural"));
                ui.link(cards,"Распознавание речи","Движки и модели для команд",()->openSection("speech"));
                ui.link(cards,"Озвучка","Голос, движок и скорость",()->openSection("voice"));
                ui.link(cards,"Голосовой вызов","Фразы активации и работа в фоне",()->openSection("assistant"));
                ui.link(cards,"Устройства и подключения","Сопряжение и проверка связи с ПК",()->openSection("pc"));
                ui.link(cards,"Разрешения и безопасность","Системные доступы и согласия",()->openSection("permissions"));
                ui.link(cards,"Мастер настройки","Разрешения, голос и модели",()->openSection("setup"));
                ui.link(cards,"Оформление","Темы WileyAI",this::chooseTheme);
                ui.link(cards,"Диагностика","Журнал работы и экспорт",this::showDiagnostics);
                ui.link(cards,"О приложении",ReleaseUpdates.state().offer()==null?"Версия, обновления и обратная связь":
                        "Доступно обновление WileyAI",()->openSection("about"));
                ui.link(cards,"Дополнительно","Проверки и резервная модель",()->openSection("advanced"));
        }
        if (!section.equals("setup")) navigation(sectionTab(section));
        trackDiagnosticScreenDraw(diagnosticScreenBegan);
    }
    private String sectionTab(String section){
        if(screenTrail.contains("personal"))return "personal";
        if(screenTrail.contains("settings"))return "settings";
        return switch(section){
            case "personal","profile","memory","communication","apps","app_defaults","media","notes","guide","levels" -> "personal";
            default -> "settings";
        };
    }

    private AssistantPanel createAssistantPanel() {
        return new AssistantPanel(this, ui, runtimeAccess, () -> speechModels.active() != null,
                () -> speechPanel().confirmDownload(), () -> openSection("speech"));
    }

    private void setupStep(int step) {
        if (!canNavigate()) return;
        firstRun.step(step);
        showSection("setup");
    }

    private void finishSetup() {
        if (!canNavigate()) return;
        firstRun.finish();
        if (!screenTrail.isEmpty() && screenTrail.peekLast().equals("settings")) {
            screenTrail.removeLast();
            showSection("settings");
        }
        else showChat();
        showDiagnosticNotice();
    }

    private void renderSetup(LinearLayout cards) {
        int step = firstRun.step();
        cards.addView(ui.text("Шаг " + (step + 1) + " из 5", 14, ui.theme.accentText));
        switch (step) {
            case 0 -> ui.card(cards, "Добро пожаловать!", "Попросите Вайли открыть приложение, назвать время или помочь в чате. Можно начать с текста и настроить голос позже.");
            case 1 -> renderSetupPermissions(cards);
            case 2 -> renderSetupComponents(cards);
            case 3 -> {
                assistantPanel = createAssistantPanel();
                assistantPanel.renderSetup(cards);
            }
            case 4 -> renderSetupSummary(cards);
            default -> throw new IllegalStateException("Invalid setup step");
        }
        cards.addView(ui.button(step == 0 ? "Начать настройку" : step == FirstRunSetup.LAST
                ? "Начать пользоваться Вайли" : "Далее", step == FirstRunSetup.LAST ? this::finishSetup : () -> setupStep(step + 1)));
        if (step > 0) cards.addView(ui.button("Предыдущий шаг", () -> setupStep(step - 1)));
        if (step < FirstRunSetup.LAST) cards.addView(ui.button("Настроить позже", this::finishSetup));
    }

    private void renderSetupPermissions(LinearLayout cards) {
        ui.card(cards, "Разрешения Android", "Каждое разрешение можно дать отдельно. Для текстового чата они не нужны.");
        var updates = new java.util.ArrayList<Runnable>();
        for (RuntimeAccess.Item item : RuntimeAccess.Item.values()) {
            TextView state = ui.text("", 15, ui.theme.accentText);
            Button grant = ui.button("Разрешить " + item.title.toLowerCase(java.util.Locale.ROOT),
                    () -> runtimeAccess.request(item, ui, this::refreshSetupAndPermissions));
            ui.card(cards, item.title, item.description);
            cards.addView(state);
            cards.addView(grant);
            updates.add(() -> {
                state.setText(runtimeAccess.status(item));
                grant.setVisibility(runtimeAccess.granted(item) ? View.GONE : View.VISIBLE);
            });
        }
        setupRefresh = () -> updates.forEach(Runnable::run);
        setupRefresh.run();
    }

    private void renderSetupComponents(LinearLayout cards) {
        ui.card(cards, "Основные компоненты", "Выберите, чем пользоваться. Загрузка начнётся только после подтверждения.");
        LinearLayout recognition = ui.disclosure(cards,"Распознавание речи");
        ui.card(recognition,"Vosk", "Понимает команды и фразу фонового вызова. Загрузка 44,1 МиБ.");
        TextView voskState = ui.text("",14,ui.theme.secondary);
        recognition.addView(voskState);
        recognition.addView(ui.button("Скачать или продолжить Vosk", () -> speechPanel().confirmDownload()));
        Button pauseVosk = ui.button("Приостановить Vosk", speechModels::pause);
        recognition.addView(pauseVosk);
        ui.card(recognition,"GigaAM v3", "Рекомендуем для русских команд. Работает без интернета. Загрузка " + GigaAmModel.sizeText() + " МиБ.");
        TextView gigaState = ui.text("",14,ui.theme.secondary);
        recognition.addView(gigaState);
        recognition.addView(ui.button("Скачать или продолжить GigaAM", () -> speechPanel().confirmGigaAmDownload()));
        Button pauseGiga = ui.button("Приостановить GigaAM", asrModels::pause);
        recognition.addView(pauseGiga);
        recognition.addView(ui.button("Выбрать распознавание или управлять загрузкой", () -> openSection("speech")));

        LinearLayout synthesis = ui.disclosure(cards,"Озвучка ответов");
        ui.card(synthesis,"Системная озвучка", "Для работы без интернета нужен установленный русский голос Android.");
        TextView voiceState = ui.text("",14,ui.theme.secondary);
        synthesis.addView(voiceState);
        synthesis.addView(ui.button("Выбрать и прослушать голос", () -> openSection("voice")));

        LinearLayout neural = ui.disclosure(cards,"Локальная нейросеть");
        ui.card(neural,"Qwen3 0.6B", "Для разговоров без интернета. Загрузка 378,3 МиБ. Голосовые команды и простые действия могут работать без этой модели.");
        TextView llmState = ui.text("",14,ui.theme.secondary);
        neural.addView(llmState);
        neural.addView(ui.button("Скачать Qwen или выбрать совместимый GGUF", () -> openSection("llm")));
        neural.addView(ui.button("Продолжить без разговорной модели", () -> setupStep(3)));
        setupRefresh = () -> {
            voskState.setText(speechModels.detail());
            gigaState.setText(asrModels.detail());
            llmState.setText(llmModels.status());
            voiceState.setText(setupVoiceState());
            pauseVosk.setVisibility(speechModels.busy() ? View.VISIBLE : View.GONE);
            pauseGiga.setVisibility(asrModels.busy() ? View.VISIBLE : View.GONE);
        };
        setupRefresh.run();
        localVoice.inspect(this::refreshSetupAndPermissions);
    }

    private void renderSetupSummary(LinearLayout cards) {
        ui.card(cards, "Всё готово к началу", "Здесь видно, какие функции уже доступны и что можно добавить позже.");
        TextView summary = ui.text("",16,ui.theme.text);
        cards.addView(summary);
        setupTrialStatus = ui.text("Скажите «Сколько сейчас времени?» после приглашения.",14,ui.theme.secondary);
        cards.addView(setupTrialStatus);
        cards.addView(ui.button("Проверить голосовую команду", this::startSetupTrial));
        cards.addView(ui.button("Открыть озвучку", () -> openSection("voice")));
        setupRefresh = () -> summary.setText("Микрофон · " + runtimeAccess.status(RuntimeAccess.Item.MIC)
                + "\nРаспознавание · " + selectedSpeechState()
                + "\nОзвучка · " + setupVoiceState()
                + "\nРазговорная модель · " + (llmModels.active() != null && LocalLlmNative.supported() ? "файл установлен. Ответ можно проверить в чате" : "локальная модель не готова. Команды доступны")
                + "\nГолосовой вызов · " + (HandsFreeService.running() ? HandsFreeService.status() : "служба не запущена"));
        setupRefresh.run();
        localVoice.inspect(this::refreshSetupAndPermissions);
    }

    private String setupVoiceState() {
        return localVoice.voices().isEmpty() ? "русский офлайн-голос пока не подтверждён" : "доступен русский голос · " + localVoice.engineLabel();
    }

    private String selectedSpeechState() {
        return switch (settings.preferences.getInt("asr_engine", 0)) {
            case 1 -> SystemSpeechEngine.available(this,false) ? "служба Android доступна, может использовать сеть" : "служба Android недоступна";
            case 2 -> SystemSpeechEngine.available(this,true) ? "доступно распознавание Android на устройстве" : "офлайн-распознавание Android недоступно";
            case 3 -> asrModels.active() == null ? "нужна модель GigaAM" : "файл GigaAM установлен. Проверьте командой";
            default -> speechModels.active() == null ? "нужен комплект Vosk" : "комплект Vosk установлен. Проверьте командой";
        };
    }

    private void startSetupTrial() {
        if (setupTrialStatus == null) return;
        if (recognitionBusy()) {
            if (systemSpeech.busy()) systemSpeech.cancel(); else if (gigaAmSpeech.busy()) gigaAmSpeech.cancel(); else offlineSpeech.cancel();
            setupTrialStatus.setText("Проверка остановлена. Можно попробовать снова.");
            return;
        }
        int engine = settings.preferences.getInt("asr_engine", 0);
        if (!checkSpeechSetup(engine)) return;
        if (!runtimeAccess.granted(RuntimeAccess.Item.MIC)) {
            runtimeAccess.request(RuntimeAccess.Item.MIC,ui,this::startSetupTrial);
            return;
        }
        TextView target = setupTrialStatus;
        target.setText("Подготавливаю микрофон…");
        Runnable start = () -> {
            if (!resumed || setupTrialStatus != target) { releaseManualWake(); return; }
            startSelectedSpeech(engine, new OfflineSpeechEngine.Listener() {
                public void ready(Runnable begin) { state("Говорите сейчас"); begin.run(); }
                public void state(String text) { if (setupTrialStatus == target) target.setText(text); }
                public void partial(String text) {}
                public void error(String text) { state(text); }
                public void result(String text) {
                    if (setupTrialStatus != target || !resumed) return;
                    PhoneCommands.Action time = PhoneCommands.parse(text,true);
                    if (time == null || !"info".equals(time.kind) || !"time".equals(time.value)) {
                        state("Попробуйте ещё раз сказать «Сколько сейчас времени?».");
                        return;
                    }
                    new PhoneActionEngine(MainActivity.this, answer -> {
                        state(answer);
                        if (!localVoice.voices().isEmpty()) localVoice.speak(answer);
                        else state(answer + " · Русский офлайн-голос пока не доступен.");
                    }, appCatalog,
                            () -> resumed && setupTrialStatus == target).execute(time);
                }
                public void finished() { releaseManualWake(); }
            });
        };
        if (HandsFreeService.running()) {
            if (manualWakeSuspended) return;
            manualWakeSuspended = true;
            HandsFreeService.pauseExternal(start);
        } else start.run();
    }

    private BrainPanel createBrainPanel(){
        return new BrainPanel(this,ui,()->openSection("llm"),()->openSection("cloud"),
            ()->openSection("connections"),()->localMode=true);
    }
    private void openPcRecords(boolean tasks){
        if(!canNavigate())return;
        if(profile==null){openSection("pc");return;}
        localMode=false;
        phoneTarget=false;
        showChat();
        showItems(tasks);
    }
    private void trackDiagnosticScreenDraw(long began){
        if(!DiagnosticLog.enabled()||root==null)return;View screen=root;
        screen.getViewTreeObserver().addOnPreDrawListener(new android.view.ViewTreeObserver.OnPreDrawListener(){
            public boolean onPreDraw(){if(screen.getViewTreeObserver().isAlive())screen.getViewTreeObserver().removeOnPreDrawListener(this);if(root==screen)DiagnosticLog.event(DiagnosticJournal.Event.SCREEN_OPEN_MS,android.os.SystemClock.elapsedRealtime()-began);return true;}
        });
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
    private void showDiagnostics() { showDiagnosticControls(); }
    private void showDiagnosticControls() {
        if(isFinishing() || isDestroyed())return;
        LinearLayout box=vertical();padded(box,12);
        final android.app.AlertDialog[] holder=new android.app.AlertDialog[1];
        long since=DiagnosticLog.startedAt();
        long endTime=DiagnosticLog.enabled()?System.currentTimeMillis():DiagnosticLog.stoppedAt();
        long minutes=since>0&&endTime>=since?(endTime-since)/60000:0;
        box.addView(text("Сбор: "+(DiagnosticLog.enabled()?"включён":"выключен")+(since>0?"\nНачат: "+android.text.format.DateFormat.format("dd.MM.yyyy HH:mm",since)+" · длительность: "+minutes+" мин":(DiagnosticLog.enabled()?"\nЗапись включена автоматически":"\nЗапись ещё не начиналась")),15,ui.theme.text));
        TextView journalSize=text("Размер журнала…",14,ui.theme.secondary);
        box.addView(journalSize);
        android.widget.Switch diagnosticSwitch=new android.widget.Switch(this);diagnosticSwitch.setText("Диагностика включена");diagnosticSwitch.setTextColor(ui.theme.text);diagnosticSwitch.setChecked(DiagnosticLog.enabled());diagnosticSwitch.setOnCheckedChangeListener((v,checked)->{if(checked)DiagnosticLog.start();else DiagnosticLog.stop();});ui.styleControl(diagnosticSwitch); box.addView(diagnosticSwitch);
        box.addView(text("Последняя запись: "+(DiagnosticLog.lastEvent()>0?android.text.format.DateFormat.format("dd.MM.yyyy HH:mm",DiagnosticLog.lastEvent()):"нет данных в текущем сеансе"),14,ui.theme.secondary));
        box.addView(button("Скачать лог",()->DiagnosticLog.preview(this::previewDiagnostic)));
        box.addView(button("Поделиться логом",()->DiagnosticLog.preview(this::previewDiagnostic)));
        box.addView(button("Ложное пробуждение",()->DiagnosticLog.markLastWakeFalse(message->{
            if(!isFinishing()&&!isDestroyed())android.widget.Toast.makeText(this,message,android.widget.Toast.LENGTH_SHORT).show();
        })));
        box.addView(button("Обучение голосового вызова",()->{if(holder[0]!=null)holder[0].dismiss();startActivity(new Intent(this,WakeSampleActivity.class));}));
        box.addView(button("Сравнение голосового вызова",()->{if(holder[0]!=null)holder[0].dismiss();startActivity(new Intent(this,WakeComparisonActivity.class));}));
        box.addView(button("Акустическая диагностика",()->{if(holder[0]!=null)holder[0].dismiss();startActivity(new Intent(this,AcousticDiagnosticsActivity.class));}));
        box.addView(button("Очистить",()->ui.dialog().setMessage("Удалить локальный диагностический журнал?").setNegativeButton("Отмена",null).setPositiveButton("Очистить",(d,w)->DiagnosticLog.clear(()->{if(holder[0]!=null)holder[0].dismiss();showDiagnosticControls();})).show()));
        holder[0]=ui.dialog().setTitle("Диагностика телефона").setView(box).setPositiveButton("Закрыть",null).show();
        background(()->{
            long bytes=DiagnosticLog.storageBytes();
            onUi(()->{
                if(holder[0].isShowing())journalSize.setText(bytes<0?"Размер журнала недоступен":"Размер журнала: "+bytes+" байт");
            });
        });
    }
    private void previewDiagnostic(String report){
        if(isFinishing()||isDestroyed())return;
        if(report.startsWith("Не удалось подготовить журнал")){error(report);return;}
        TextView content=text(report,12,ui.theme.text);content.setTextIsSelectable(true);content.setPadding(dp(12),dp(12),dp(12),dp(12));
        ScrollView preview=new ScrollView(this);preview.addView(content);
        ui.dialog().setTitle("Предпросмотр диагностического файла").setView(preview).setNegativeButton("Отмена",null).setPositiveButton("Сохранить TXT",(dialog,which)->{
            pendingDiagnosticExport=report;String name="WileyAI_Log_"+java.time.LocalDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm"))+".txt";
            Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("text/plain").putExtra(Intent.EXTRA_TITLE,name);
            try{startActivityForResult(save,DIAGNOSTIC_EXPORT);}catch(Exception e){pendingDiagnosticExport=null;error("Не удалось открыть системное сохранение файла.");}
        }).setNeutralButton("Поделиться",(dialog,which)->shareDiagnostic(report)).show();
    }
    private void shareDiagnostic(String report) {
        background(()->{try {
            java.io.File file=new java.io.File(getCacheDir(),"wileyai-diagnostic-share.txt");
            try(java.io.OutputStream out=new java.io.FileOutputStream(file,false)){out.write(report.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
            Uri uri=new Uri.Builder().scheme("content").authority(getPackageName()+".diagnostics").appendPath("log.txt").build();
            Intent send=new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_STREAM,uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            send.setClipData(android.content.ClipData.newRawUri("WileyAI log",uri));onUi(()->{try{startActivity(Intent.createChooser(send,"Поделиться журналом"));}catch(Exception e){error("Не удалось открыть меню отправки.");}});
        } catch(Exception e){onUi(()->error("Не удалось подготовить журнал."));}});
    }
    private void chooseTheme() {
        LinearLayout content=vertical();content.setPadding(dp(12),dp(4),dp(12),dp(8));
        android.widget.Switch artistic=new android.widget.Switch(this);artistic.setText("Художественный фон");artistic.setTextColor(ui.theme.text);artistic.setMinHeight(dp(48));artistic.setChecked(settings.preferences.getBoolean("art_background",true));ui.styleControl(artistic); content.addView(artistic);
        android.widget.Switch live=new android.widget.Switch(this);live.setText("Живой фон");live.setTextColor(ui.theme.text);live.setMinHeight(dp(48));live.setChecked(settings.preferences.getBoolean("art_animation",true));live.setEnabled(artistic.isChecked());ui.styleControl(live); content.addView(live);
        final boolean[] changed={false};final android.app.AlertDialog[] holder=new android.app.AlertDialog[1];
        artistic.setOnCheckedChangeListener((v,on)->{settings.preferences.edit().putBoolean("art_background",on).apply();live.setEnabled(on);changed[0]=true;});
        live.setOnCheckedChangeListener((v,on)->{settings.preferences.edit().putBoolean("art_animation",on).apply();changed[0]=true;});
        int[] thumbs={0,R.drawable.theme_thumb_aurora,R.drawable.theme_thumb_ice,R.drawable.theme_thumb_ember,R.drawable.theme_thumb_nebula};
        for(int i=0;i<WileyTheme.NAMES.length;i++){
            final int index=i;LinearLayout item=ui.row();item.setPadding(dp(8),dp(4),dp(8),dp(4));item.setMinimumHeight(dp(56));item.setBackground(ui.interactive(android.graphics.Color.TRANSPARENT,ui.theme.high,12));item.setFocusable(true);
            if(thumbs[i]!=0){android.widget.ImageView thumbnail=new android.widget.ImageView(this);thumbnail.setImageResource(thumbs[i]);thumbnail.setScaleType(android.widget.ImageView.ScaleType.CENTER_CROP);LinearLayout.LayoutParams imageParams=new LinearLayout.LayoutParams(dp(40),dp(68));imageParams.setMargins(0,0,dp(12),0);item.addView(thumbnail,imageParams);}
            TextView label=text(WileyTheme.NAMES[i]+(settings.theme().equals(WileyTheme.IDS[i])?" · выбрана":""),16,ui.theme.text);item.addView(label,new LinearLayout.LayoutParams(0,-2,1));
            item.setContentDescription(WileyTheme.NAMES[i]);item.setOnClickListener(v->{if(!settings.theme().equals(WileyTheme.IDS[index])){settings.theme(WileyTheme.IDS[index]);changed[0]=true;}holder[0].dismiss();});content.addView(item);
        }
        ScrollView scrollView=new ScrollView(this);scrollView.addView(content);
        holder[0]=ui.dialog().setTitle("Оформление WileyAI").setView(scrollView).setPositiveButton("Готово",null).create();
        holder[0].setOnDismissListener(dialog->{if(changed[0]&&!isFinishing()&&!isDestroyed()){ui=new MobileUi(this,settings.theme());showSection("settings");}});holder[0].show();
    }
    private SpeechPanel speechPanel() {
        return new SpeechPanel(this, ui, speechModels, asrModels, this::recognitionBusy, settings.preferences, () -> {
            Intent file = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE)
                .putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/octet-stream", "application/x-zip-compressed"});
            try { startActivityForResult(file, SPEECH_IMPORT); } catch (Exception e) { error("На устройстве нет приложения для выбора ZIP-файла"); }
        }, () -> {
            Intent file = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE)
                .putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/octet-stream", "application/x-zip-compressed"});
            try { startActivityForResult(file, GIGAAM_IMPORT); } catch (Exception e) { error("На устройстве нет приложения для выбора ZIP-файла"); }
        });
    }
    private void saveFeedback(byte[] archive) {
        pendingFeedback = archive;
        try {
            startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/zip")
                    .addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE, "WileyAI-feedback.zip"), FEEDBACK_EXPORT);
        } catch (Exception unavailable) { pendingFeedback = null; error("Системное сохранение файла недоступно."); }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == FEEDBACK_EXPORT) {
            byte[] archive = pendingFeedback;
            pendingFeedback = null;
            if (result == RESULT_OK && data != null && data.getData() != null) {
                if (archive == null) { error("Предпросмотр устарел. Подготовьте отчёт снова."); return; }
                Uri uri = data.getData();
                background(() -> {
                    try (var output = getContentResolver().openOutputStream(uri, "w")) {
                        if (output == null) throw new java.io.IOException();
                        output.write(archive);
                        onUi(() -> note("Архив отчёта сохранён."));
                    } catch (Exception unavailable) { onUi(() -> error("Не удалось записать ZIP.")); }
                });
            }
            return;
        }
        if(request==DIAGNOSTIC_EXPORT){String report=pendingDiagnosticExport;pendingDiagnosticExport=null;if(result==RESULT_OK && data!=null && data.getData()!=null && report!=null){Uri destination=data.getData();background(()->{try(java.io.OutputStream out=getContentResolver().openOutputStream(destination,"w")){if(out==null)throw new java.io.IOException();out.write(report.getBytes(java.nio.charset.StandardCharsets.UTF_8));onUi(()->note("Диагностический файл сохранён"));}catch(Exception e){onUi(()->error("Не удалось сохранить диагностический файл."));}});}else if(result==RESULT_OK && report==null)error("Предпросмотр устарел. Откройте его ещё раз.");return;}
        if (request == SPEECH_IMPORT && result == RESULT_OK && data != null && data.getData() != null && !speechModels.busy() && !recognitionBusy()) speechModels.importZip(data.getData());
        if (request == GIGAAM_IMPORT && result == RESULT_OK && data != null && data.getData() != null && !asrModels.busy() && !recognitionBusy()) asrModels.importZip(data.getData());
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
                onUi(() -> { if (network != null && current == profile && !localMode) {pcHealth=ChatReadiness.State.READY; network.setText("ПК · " + elapsed + " мс");} });
            } catch (Exception e) { onUi(() -> { if (network != null && current == profile && !localMode) {pcHealth=ChatReadiness.State.UNAVAILABLE; network.setText("ПК недоступен");} }); }
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
        TextView bubble = text(content, 16, ui.theme.text); bubble.setTextIsSelectable(true); bubble.setPadding(dp(12), dp(9), dp(12), dp(9));
        bubble.setBackground(ui.bubble(role.equals("user") ? ui.theme.high : ui.theme.low));
        if (role.equals("assistant")) MessageRenderer.render(bubble, content);
        bubble.setOnLongClickListener(v -> {
            ui.dialog().setTitle(role.equals("user") ? "Ваше сообщение" : "Ответ Уайли")
                .setItems(role.equals("user") ? new String[]{"Копировать", "Изменить и отправить заново"} : new String[]{"Копировать"}, (d, index) -> {
                    if (index == 0) ((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(android.content.ClipData.newPlainText("WileyAI", bubble.getText()));
                    else if (!chatting.get() && composer != null) { composer.setText(content); composer.setSelection(composer.length()); composer.requestFocus(); }
                }).setNegativeButton("Закрыть", null).show(); return true;
        });
        bubble.setMaxWidth((int)(getResources().getDisplayMetrics().widthPixels*.84f));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-2, -2);params.gravity=role.equals("user")?Gravity.END:Gravity.START;params.setMargins(0,0,0,dp(8));messages.addView(bubble,params);
        LinearLayout messageParent=messages;messageParent.post(()->{if(messageParent.getWidth()>0)bubble.setMaxWidth((int)((messageParent.getWidth()-messageParent.getPaddingLeft()-messageParent.getPaddingRight())*.86f));});
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN)); return bubble;
    }
    private void send() {
        String value = composer.getText().toString().trim();
        if (value.isEmpty() || chatting.get() || recognitionBusy() || (localMode && !localReady)) return;
        PersonalPreferences personal=new PersonalPreferences(this);
        String identity=ProfileIdentity.answer(value,personal.name(),personal.address());
        if(identity!=null){composer.setText("");addMessage("user",value);addMessage("assistant",identity);return;}
        MemoryCommand.Request memoryRequest=MemoryCommand.parse(value);
        if(memoryRequest!=null){handleMemoryCommand(memoryRequest);return;}
        if(MemoryCommand.ambiguousMutation(value)){note("Для изменения памяти скажите «запомни, что…» или «забудь, что…».");return;}
        if(ScreenRequest.classify(value)!=ScreenRequest.Kind.NONE){
            composer.setText("");addMessage("user",value);
            ScreenDispatcher.dispatch(this,appCatalog,value,()->!destroyed&&resumed&&page.equals("chat"),reply->{addMessage("assistant",reply);note("Наблюдение не сохраняется в истории");if(readAloud)localVoice.speak(reply);});
            return;
        }
        if (localMode) {
            localChats.submit(value, id -> {
                if (composer != null && composer.getText().toString().trim().equals(value)) composer.setText("");
                PhoneCommands.Action action = StructuredActionAdapter.requiresPlan(value)?null:PhoneCommands.parse(value, true);
                if (action != null) new PhoneActionEngine(this, message -> localReply(id, message), appCatalog, () -> resumed).execute(action);
                else if (new ModelManager(this).selected()!=BrainProvider.Kind.LOCAL || (llmModels.active() != null && !llmModels.busy())) generateLocal(id);
                else {
                    localReply(id, llmModels.busy() ? "Разговорная модель ещё загружается." : "Для свободного разговора нужна модель. Системные команды уже доступны.");
                    SetupAction.show(ui,"Разговорная модель", "Можно установить Qwen для разговоров без интернета или пользоваться командами телефона.",
                            "Выбрать модель", () -> openSection("llm"), "Продолжить без неё", () -> {});
                }
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
        logoStart();composer.setText(""); addMessage("user", value); streaming = addMessage("assistant", "");
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
                onUi(() -> { if (selected.equals(conversation) && streaming != null) MessageRenderer.render(streaming, lastAnswer); note("Ответ получен");logoEnd(true); });
                String speech = actionSpeech[0] ? ("off".equals(speechPreference[0]) ? "" : "full".equals(speechPreference[0]) ? lastAnswer : spokenResult[0]) : lastAnswer;
                if ((readAloud || forceRead[0]) && !speech.isEmpty() && selected.equals(conversation) && resumed) {
                    if (settings.preferences.getBoolean("pc_local_voice", false)) { String spoken = speech; onUi(() -> { if (resumed && selected.equals(conversation)) localVoice.speak(spoken); }); }
                    else speak(speech);
                }
            } catch (Exception e) { onUi(() -> { note(e.getMessage());logoEnd(false); if (streaming != null && answer.length() == 0) streaming.setText(e.getMessage()); }); }
            finally { gateway.activeChat = null; chatting.set(false); requestId = ""; onUi(() -> { if (send != null) send.setEnabled(true); if (stop != null) stop.setVisibility(View.GONE); }); }
        });
    }
    private void handleMemoryCommand(MemoryCommand.Request request){
        PersonalPreferences memory=new PersonalPreferences(this);
        if(request.kind()==MemoryCommand.Kind.SAVE){
            ui.dialog().setTitle("Сохранить воспоминание?").setMessage(request.text()).setNegativeButton("Отмена",null)
                .setPositiveButton("Сохранить",(dialog,which)->{
                    try{memory.saveMemory(null,request.text());composer.setText("");note("Воспоминание сохранено на телефоне");}
                    catch(IllegalStateException failure){error(failure.getMessage());}
                }).show();return;
        }
        java.util.List<PersonalPreferences.Memory> records;
        try{records=memory.memories();}catch(IllegalStateException failure){error(failure.getMessage());return;}
        if(request.kind()==MemoryCommand.Kind.LIST){
            String content=records.isEmpty()?"Воспоминаний пока нет.":android.text.TextUtils.join("\n\n",records.stream().map(PersonalPreferences.Memory::text).toArray(String[]::new));
            ui.dialog().setTitle("Память WileyAI").setMessage(content).setPositiveButton("Закрыть",null).show();return;
        }
        java.util.List<PersonalPreferences.Memory> matches=new java.util.ArrayList<>();
        for(var record:records)if(MemoryCommand.matches(record.text(),request.text()))matches.add(record);
        if(matches.isEmpty()){ui.dialog().setMessage("Подходящее воспоминание не найдено.").setPositiveButton("Закрыть",null).show();return;}
        java.util.function.Consumer<PersonalPreferences.Memory> confirm=record->ui.dialog().setTitle("Удалить воспоминание?").setMessage(record.text())
            .setNegativeButton("Отмена",null).setPositiveButton("Удалить",(d,w)->{try{memory.removeMemory(record.id());composer.setText("");note("Воспоминание удалено");}catch(IllegalStateException failure){error(failure.getMessage());}}).show();
        if(matches.size()==1)confirm.accept(matches.get(0));else ui.dialog().setTitle("Выберите воспоминание")
            .setItems(matches.stream().map(PersonalPreferences.Memory::text).toArray(String[]::new),(d,i)->confirm.accept(matches.get(i)))
            .setNegativeButton("Отмена",null).show();
    }
    private void stopChat() {
        DiagnosticLog.event(DiagnosticJournal.Event.MODEL_CANCEL,0);logoCancelled=true;logoState(NeonVoiceView.Mode.IDLE);
        if(brain!=null&&brain.busy()){brain.cancel();note("Останавливаю план…");return;}
        if(gatewayChat.busy()){gatewayChat.cancelPending(this::note);note("Останавливаю ответ Gateway…");return;}
        if(cloudChat.busy()){cloudChat.cancel();note("Останавливаю облачный ответ…");return;}
        if (localLlm.busy()) { localLlm.cancel(); note("Останавливаю локальный ответ…"); return; }
        String id = requestId; if (id.isEmpty()) return;
        note("Останавливаю ответ…");
        background(() -> { try { jsonRequest("/chat/stop", "POST", new JSONObject().put("request_id", id)); } catch (Exception e) { onUi(() -> note(e.getMessage())); } });
    }

    private void phoneReply(String message) { addMessage("assistant", message); note("Команда телефона · локально, без сохранения в истории"); if(readAloud && resumed) localVoice.speak(message); }
    private void generateLocal(String id) {
        if (HandsFreeService.answering()) { localReply(id, "Дождитесь окончания голосового ответа помощника."); return; }
        if (!chatting.compareAndSet(false, true)) return;
        logoStart();stop.setVisibility(View.VISIBLE); send.setEnabled(false); composer.setEnabled(false);
        localChats.context(id, context -> {
            if (destroyed) return;
            ModelManager modelManager=new ModelManager(this);
            if(modelManager.selected()==BrainProvider.Kind.LOCAL&&(!resumed||!page.equals("chat")||!localMode)){finishLocalAnswer();return;}
            if(modelManager.automatic()||modelManager.toolsAllowed()||modelManager.selected()==BrainProvider.Kind.ACCOUNT_OAUTH){
                streaming=addMessage("assistant","Понимаю просьбу…");
                brain.generate(context,new BrainController.Host(){
                    public boolean active(){return !destroyed;}
                    public void state(String text){note(text);}
                    public void confirm(String plan,java.util.function.Consumer<Boolean> reply){if(!resumed||destroyed){reply.accept(false);return;}ui.dialog().setTitle("Выполнить план?").setMessage(plan).setNegativeButton("Отмена",(d,w)->reply.accept(false)).setOnCancelListener(d->reply.accept(false)).setPositiveButton("Выполнить",(d,w)->reply.accept(true)).show();}
                    public void launch(Intent intent){if(destroyed||((android.app.KeyguardManager)getSystemService(KEYGUARD_SERVICE)).isDeviceLocked())throw new IllegalStateException();startActivity(intent);}
                    public void done(String text){logoEnd(true);localReply(id,text);}
                    public void error(String text){logoEnd(false);localReply(id,text);}
                    public void declined(String text){logoTerminal=true;logoState(NeonVoiceView.Mode.ERROR);localReply(id,text);}
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
                public void done(String text, boolean stopped) { if(stopped){logoCancelled=true;logoState(NeonVoiceView.Mode.IDLE);}else logoEnd(text!=null&&!text.isEmpty()); if(remote&&gatewayChat.savedResponse()){localChats.load();if(readAloud&&resumed&&localMode)localVoice.speak(text);}else localReply(id, text.isEmpty() ? "Ответ остановлен или не получен. Попробуйте короткий вопрос." : text + (stopped ? "\n\n[Ответ остановлен]" : "")); }
                public void error(String text) { logoEnd(false);localReply(id, text); }
                public void finished() { finishLocalAnswer(); }
            };
            if(remote)gatewayChat.generate(id,context,listener);else if(cloud)cloudChat.generate(context,listener);else localLlm.generate(llmModels.active(),LocalLlm.prompt(context,new PersonalPreferences(this).localResponseContext(context.isEmpty()?"":context.get(context.size()-1).content())),listener);
        });
    }
    private String phoneModeLabel(){if(new ModelManager(this).selected()==BrainProvider.Kind.ACCOUNT_OAUTH)return new ModelManager(this).label()+"  ▾";if(GatewayClient.enabled(this)){try{JSONObject selected=settings.readGateway();return selected==null?"Gateway · настройка  ▾":selected.optString("provider_name","Gateway")+" · "+selected.optString("model_name","выберите модель")+"  ▾";}catch(Exception ignored){return "Gateway · проверить подключение  ▾";}}if(CloudChat.enabled(this))return "Телефон · облачный чат  ▾";return llmModels.active()!=null?"Телефон · Qwen3 0.6B  ▾":"Телефон · без разговорной модели  ▾";}
    private void finishLocalAnswer() { if(!logoTerminal)logoState(NeonVoiceView.Mode.IDLE);chatting.set(false); if (send != null) send.setEnabled(localReady); if (composer != null) composer.setEnabled(localReady); if (stop != null) stop.setVisibility(View.GONE); note("Готово · "+new ModelManager(this).label()); }
    private void localReply(String id, String message) { localChats.reply(id, message); if (readAloud && resumed && localMode) localVoice.speak(message); }
    private void setRecordIcon(boolean recording) {if(record!=null)ui.controlIcon(record,recording?R.drawable.ui_stop:R.drawable.ui_mic);}
    private void toggleRecording() {
        if (recognitionBusy()) { if (systemSpeech.busy()) systemSpeech.finish(); else if (gigaAmSpeech.busy()) gigaAmSpeech.finish(); else offlineSpeech.finish(); note("Завершаю распознавание…"); return; }
        if (recorder != null) { finishRecording(); return; }
        if (manualWakeSuspended) { note("Подготавливаю микрофон…"); return; }
        if (HandsFreeService.running()) {
            if (WileyVoiceService.invoke()) return;
            if (!localMode) { note("Голосовое окно недоступно. Откройте настройки голосового помощника."); return; }
            if (chatting.get()) { note("Дождитесь ответа перед записью"); return; }
            if (!runtimeAccess.granted(RuntimeAccess.Item.MIC)) { runtimeAccess.request(RuntimeAccess.Item.MIC,ui,this::toggleRecording); return; }
            int engine=settings.preferences.getInt("asr_engine",0);
            if (!checkSpeechSetup(engine)) return;
            note("Голосовое окно недоступно. Запускаю распознавание в чате…");
            manualWakeSuspended=true;
            HandsFreeService.pauseExternal(() -> {
                if(destroyed || !resumed || !localMode || !page.equals("chat") || composer==null) { releaseManualWake(); return; }
                beginLocalRecognition();
                if(!recognitionBusy()) releaseManualWake();
            });
            return;
        }
        if (localMode && !checkSpeechSetup(settings.preferences.getInt("asr_engine",0))) return;
        if (!localMode && profile == null) { showPair(""); return; }
        if (chatting.get()) { note("Дождитесь ответа перед записью"); return; }
        if (!runtimeAccess.granted(RuntimeAccess.Item.MIC)) {
            runtimeAccess.request(RuntimeAccess.Item.MIC,ui,() -> { if (page.equals("chat")) toggleRecording(); });
            return;
        }
        if (localMode) beginLocalRecognition(); else beginRecording();
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        runtimeAccess.returned(code, permissions, results, ui, this::refreshSetupAndPermissions);
    }

    private boolean checkSpeechSetup(int engine) {
        Runnable settings = () -> openSection("speech");
        if (engine == 0 && (speechModels.active() == null || speechModels.busy())) {
            SetupAction.show(ui,"Нужен русский комплект Vosk", speechModels.detail(),
                    "Распознавание речи", settings, speechModels.busy() ? null : "Скачать Vosk",
                    speechModels.busy() ? null : () -> speechPanel().confirmDownload());
            return false;
        }
        if (engine == 3 && (asrModels.active() == null || asrModels.busy())) {
            SetupAction.show(ui,"Нужна модель GigaAM", asrModels.detail(),
                    "Распознавание речи", settings, asrModels.busy() ? null : "Скачать GigaAM",
                    asrModels.busy() ? null : () -> speechPanel().confirmGigaAmDownload());
            return false;
        }
        if ((engine == 1 || engine == 2) && !SystemSpeechEngine.available(this,engine == 2)) {
            SetupAction.show(ui,"Распознавание Android недоступно", "Выберите Vosk или GigaAM для голосовых команд.",
                    "Распознавание речи", settings, null, null);
            return false;
        }
        return true;
    }
    private void releaseManualWake(){if(manualWakeSuspended){manualWakeSuspended=false;HandsFreeService.resumeExternal();}}
    private void beginLocalRecognition() {
        if (!localMode || destroyed || !page.equals("chat")) return;
        final int asrEngine = settings.preferences.getInt("asr_engine", 0);
        if (asrEngine == 0 && (speechModels.active() == null || speechModels.busy())) return;
        if (asrEngine == 3 && (asrModels.active() == null || asrModels.busy())) { note("Модель GigaAM не установлена. Установите её в разделе «Распознавание»."); return; }
        localVoice.stop(); releasePlayer();
        final EditText destination = composer;
        final String previous = composer.getText().toString();
        final String generation = asrEngine == 0 ? speechModels.active().getFileName().toString() : asrEngine == 3 ? "gigaam-v3" : "android-system";
        setRecordIcon(true); send.setEnabled(false); composer.setEnabled(false);
        final long diagnosticSttStarted=android.os.SystemClock.elapsedRealtime();DiagnosticLog.event(DiagnosticJournal.Event.MANUAL_STT_BEGIN,asrEngine);
        OfflineSpeechEngine.Listener recognition = new OfflineSpeechEngine.Listener() {
            public void ready(Runnable startMicrophone){
                if(!resumed||composer!=destination)return;
                if(!settings.preferences.getBoolean("assistant_listening_prompt",true)){startMicrophone.run();return;}
                java.util.concurrent.atomic.AtomicBoolean once=new java.util.concurrent.atomic.AtomicBoolean();
                Runnable begin=()->{if(!destroyed&&resumed&&composer==destination&&once.compareAndSet(false,true)){localVoice.stop();pingHandler.postDelayed(startMicrophone,160);}};
                localVoice.speakCompleted("Слушаю",begin);pingHandler.postDelayed(begin,5000);
            }
            public void state(String message) { note(message);logoState(message.contains("Распознаю")?NeonVoiceView.Mode.PROCESSING:NeonVoiceView.Mode.LISTENING); }
            public void partial(String text) { note("Слышу: " + text); }
            public void result(String text) {
                DiagnosticLog.event(DiagnosticJournal.Event.MANUAL_STT_RESULT,text.isEmpty()?0:1);DiagnosticLog.event(DiagnosticJournal.Event.MANUAL_STT_MS,android.os.SystemClock.elapsedRealtime()-diagnosticSttStarted);
                if (!resumed || !localMode || composer != destination) return;
                VoiceDiagnostics.stt(-1, asrEngine == 0 ? "Vosk" : asrEngine == 3 ? "GigaAM" : "Android", text.isEmpty() ? "пустой результат" : "готово", !text.isEmpty(), 0);
                if (text.isEmpty()) { note("Речь не распознана. Попробуйте ещё раз."); return; }
                settings.preferences.edit().putString("speech_verified_generation", generation).putLong("speech_verified_at", System.currentTimeMillis()).apply();
                composer.setText(previous.trim().isEmpty() ? text : previous + " " + text); composer.setSelection(composer.length());
                note(asrEngine == 0 ? "Распознано локально. Проверьте текст." : asrEngine == 3 ? "Распознано GigaAM (экспериментально). Проверьте текст." : "Распознано Android. Проверьте текст.");
                if (previous.trim().isEmpty() && settings.preferences.getBoolean("voice_commands", true) && PhoneCommands.parse(text, true) != null) send();
            }
            public void error(String message) { DiagnosticLog.event(DiagnosticJournal.Event.MANUAL_STT_ERROR,0);VoiceDiagnostics.stt(-1, asrEngine == 0 ? "Vosk" : asrEngine == 3 ? "GigaAM" : "Android", "ошибка распознавания", false, 0); note(message); }
            public void finished() { DiagnosticLog.event(DiagnosticJournal.Event.MANUAL_STT_END,0);releaseManualWake();if(!chatting.get())logoState(NeonVoiceView.Mode.IDLE);if (record != null) setRecordIcon(false); if (composer != null && localReady) composer.setEnabled(true); if (send != null) send.setEnabled(localReady && !chatting.get()); }
        };
        startSelectedSpeech(asrEngine, recognition);
    }

    private void startSelectedSpeech(int engine, OfflineSpeechEngine.Listener listener) {
        if (engine == 0) offlineSpeech.start(speechModels.active(), listener);
        else if (engine == 3) gigaAmSpeech.start(15000, listener);
        else systemSpeech.start(engine == 2, listener);
    }
    private void beginRecording() {
        if (destroyed || localMode || profile == null || !page.equals("chat")) return;
        try {
            recording = File.createTempFile("wiley-record-", ".m4a", getCacheDir());
            recorder = new MediaRecorder(); recorder.setAudioSource(MediaRecorder.AudioSource.MIC); recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC); recorder.setAudioSamplingRate(16000); recorder.setAudioEncodingBitRate(64000);
            recorder.setOutputFile(recording.getAbsolutePath()); recorder.setMaxDuration(60000); recorder.setOnInfoListener((r, what, extra) -> { if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED) finishRecording(); });
            recorder.prepare(); recorder.start(); setRecordIcon(true); note("Запись… Нажмите ■, чтобы завершить");
        } catch (Exception e) { if (recorder != null) recorder.release(); recorder = null; if (recording != null) recording.delete(); recording = null; error("Не удалось начать запись. Проверьте микрофон."); }
    }
    private void discardRecording() {
        if (recorder != null) { try { recorder.stop(); } catch (RuntimeException ignored) {} recorder.release(); recorder = null; }
        if (recording != null) { recording.delete(); recording = null; }
    }
    private void finishRecording() {
        if (recorder == null) return;
        try { recorder.stop(); } catch (RuntimeException e) { recorder.release(); recorder = null; if (recording != null) recording.delete(); recording = null; setRecordIcon(false); note("Запись слишком короткая"); return; }
        recorder.release(); recorder = null; setRecordIcon(false); note("Распознаю речь на компьютере…");
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
        if (tasks) { dialog.setNeutralButton(taskDone(item) ? "Вернуть в работу" : "Выполнено", (d, w) -> background(() -> {
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
        })); }
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
