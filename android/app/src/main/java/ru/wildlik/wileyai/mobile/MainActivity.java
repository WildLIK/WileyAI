package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.text.InputType;
import android.util.Base64;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLException;
import java.security.cert.CertificateException;

public final class MainActivity extends Activity {
    private static final int BG = Color.rgb(12, 10, 23), CARD = Color.rgb(30, 25, 48), ACCENT = Color.rgb(190, 168, 240);
    private static final String STORE = "wiley-mobile", KEY_ALIAS = "wileyai.mobile.connection.v1";
    private static final int MIC_PERMISSION = 71;
    private final ExecutorService io = Executors.newCachedThreadPool();
    private final AtomicBoolean chatting = new AtomicBoolean(false);
    private final AtomicBoolean pinging = new AtomicBoolean(false);
    private final Handler pingHandler = new Handler(Looper.getMainLooper());
    private final Runnable pingLoop = new Runnable() { public void run() { ping(); pingHandler.postDelayed(this, 15000); } };
    private volatile String lastWorkingHost = "";
    private JSONObject profile;
    private volatile String conversation = "";
    private String requestId = "", lastAnswer = "";
    private boolean readAloud, phoneTarget;
    private volatile HttpsURLConnection activeChat;
    private LinearLayout root, messages;
    private ScrollView scroll;
    private TextView status, title, streaming, network;
    private EditText composer;
    private Button send, record, stop;
    private MediaRecorder recorder;
    private MediaPlayer player;
    private File recording, playback;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        conversation = ""; // Start with an unsaved new chat; create it only on the first message.
        readAloud = getSharedPreferences(STORE, MODE_PRIVATE).getBoolean("read_aloud", false);
        try { profile = readProfile(); } catch (Exception ignored) { profile = null; }
        Uri incoming = getIntent() != null ? getIntent().getData() : null;
        if (incoming != null) showPair(incoming.toString());
        else if (profile == null) showPair("");
        else showChat();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        discardRecording();
        if (intent.getData() != null) showPair(intent.getData().toString());
    }

    @Override protected void onDestroy() {
        pingHandler.removeCallbacks(pingLoop);
        if (recorder != null) { try { recorder.stop(); } catch (RuntimeException ignored) {} recorder.release(); recorder = null; }
        if (recording != null) recording.delete();
        releasePlayer();
        if (activeChat != null) activeChat.disconnect();
        io.shutdownNow();
        super.onDestroy();
    }
    @Override protected void onResume() { super.onResume(); pingHandler.removeCallbacks(pingLoop); pingHandler.post(pingLoop); }
    @Override protected void onPause() { pingHandler.removeCallbacks(pingLoop); super.onPause(); }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private GradientDrawable background(int color, float radius) {
        GradientDrawable drawable = new GradientDrawable(); drawable.setColor(color); drawable.setCornerRadius(dp(radius)); return drawable;
    }
    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color); return view;
    }
    private Button button(String value, Runnable action) {
        Button result = new Button(this); result.setText(value); result.setTextSize(13); result.setAllCaps(false);
        result.setTextColor(Color.WHITE); result.setBackground(background(CARD, 12));
        result.setOnClickListener(v -> action.run()); return result;
    }
    private EditText field(String hint) {
        EditText view = new EditText(this); view.setHint(hint); view.setHintTextColor(0xffa49ab5); view.setTextColor(Color.WHITE);
        view.setTextSize(16); view.setPadding(dp(14), dp(10), dp(14), dp(10)); view.setBackground(background(CARD, 12));
        return view;
    }
    private LinearLayout vertical() { LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); return layout; }
    private LinearLayout row() { LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.HORIZONTAL); return layout; }
    private void padded(View view, int top) { view.setPadding(dp(16), dp(top), dp(16), dp(8)); }
    private void layout() { root = vertical(); root.setBackgroundColor(BG); setContentView(root); }
    private void note(String message) { if (status != null) status.setText(message); }
    private void error(String message) { runOnUiThread(() -> new AlertDialog.Builder(this).setTitle("WileyAI").setMessage(message).setPositiveButton("Понятно", null).show()); }
    private void background(Runnable work) { io.execute(work); }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias(KEY_ALIAS)) return (SecretKey) store.getKey(KEY_ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
        return generator.generateKey();
    }
    private void saveProfile(JSONObject value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] encrypted = cipher.doFinal(value.toString().getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV(), combined = new byte[iv.length + encrypted.length];
        System.arraycopy(iv, 0, combined, 0, iv.length); System.arraycopy(encrypted, 0, combined, iv.length, encrypted.length);
        if (!getSharedPreferences(STORE, MODE_PRIVATE).edit().putString("connection", Base64.encodeToString(combined, Base64.NO_WRAP)).commit())
            throw new Exception("Не удалось сохранить подключение на телефоне");
        profile = value;
    }
    private JSONObject readProfile() throws Exception {
        String encoded = getSharedPreferences(STORE, MODE_PRIVATE).getString("connection", "");
        if (encoded.isEmpty()) return null;
        byte[] combined = Base64.decode(encoded, Base64.DEFAULT);
        if (combined.length < 29) throw new Exception();
        byte[] iv = new byte[12], encrypted = new byte[combined.length - 12];
        System.arraycopy(combined, 0, iv, 0, 12); System.arraycopy(combined, 12, encrypted, 0, encrypted.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
        JSONObject value = new JSONObject(new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8));
        validateProfile(value, true); return value;
    }

    private static boolean privateIp(String host) {
        return PinnedTls.privateIp(host, false);
    }
    private static void validateProfile(JSONObject value, boolean token) throws Exception {
        JSONArray hosts = value.getJSONArray("hosts");
        if (hosts.length() == 0 || hosts.length() > 12 || value.getInt("port") != 48443 || !value.getString("fingerprint").matches("[a-f0-9]{64}")) throw new Exception("Некорректная ссылка подключения");
        for (int i = 0; i < hosts.length(); i++) if (!privateIp(hosts.getString(i))) throw new Exception("Нужен адрес локальной сети или Tailscale");
        if (token && !value.getString("token").matches("[A-Za-z0-9_-]{32,128}")) throw new Exception("Повреждено сохранённое подключение");
    }
    private static JSONObject parsePair(String value) throws Exception {
        Uri uri = Uri.parse(value.trim());
        if (!"wileyai".equals(uri.getScheme()) || !"pair".equals(uri.getHost()) || (uri.getPath() != null && !uri.getPath().isEmpty()) || uri.getFragment() != null)
            throw new Exception("Ссылка подключения должна начинаться с wileyai://pair");
        String host = uri.getQueryParameter("host"), rest = uri.getQueryParameter("addresses"), pin = uri.getQueryParameter("fingerprint"), code = uri.getQueryParameter("code");
        String port = uri.getQueryParameter("port");
        if (host == null || pin == null || code == null || port == null || !code.matches("[A-Za-z0-9_-]{20,128}")) throw new Exception("В ссылке не хватает данных подключения");
        JSONArray hosts = new JSONArray(); hosts.put(host);
        if (rest != null && !rest.isEmpty()) for (String item : rest.split(",")) if (!item.equals(host)) hosts.put(item);
        JSONObject result = new JSONObject().put("hosts", hosts).put("port", Integer.parseInt(port)).put("fingerprint", pin).put("code", code);
        validateProfile(result, false); return result;
    }
    private HttpsURLConnection open(JSONObject config, String host, String path, String method) throws Exception {
        if (!privateIp(host)) throw new Exception("Недопустимый адрес");
        return PinnedTls.open(host, config.getInt("port"), config.getString("fingerprint"), path, method, config.optString("token", ""));
    }
    private interface ConnectionWork<T> { T run(HttpsURLConnection connection) throws Exception; }
    private <T> T withConnection(JSONObject config, String path, String method, ConnectionWork<T> work) throws Exception {
        validateProfile(config, !path.equals("/pair"));
        JSONArray hosts = config.getJSONArray("hosts");
        Exception last = null;
        List<String> ordered = new ArrayList<>();
        for (int i = 0; i < hosts.length(); i++) if (hosts.getString(i).equals(lastWorkingHost)) ordered.add(lastWorkingHost);
        for (int i = 0; i < hosts.length(); i++) if (!ordered.contains(hosts.getString(i))) ordered.add(hosts.getString(i));
        for (String host : ordered) {
            HttpsURLConnection connection = null;
            try { connection = open(config, host, path, method); T result = work.run(connection); lastWorkingHost = host; return result; }
            catch (ApiException e) { throw e; }
            catch (Exception e) { last = e; }
            finally { if (connection != null) connection.disconnect(); }
        }
        if (last instanceof SSLException || (last != null && last.getCause() instanceof CertificateException)) throw new Exception("Сертификат компьютера не совпал. Создайте новый код на компьютере.");
        throw new Exception("Не удалось подключиться к компьютеру. Проверьте, что WileyAI включён и устройства находятся в одной сети Wi-Fi или Tailscale.");
    }
    private static final class ApiException extends Exception { ApiException(String message) { super(message); } }
    private static byte[] read(InputStream input, int maximum) throws Exception {
        try (InputStream source = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] block = new byte[8192]; int n;
            while ((n = source.read(block)) != -1) { if (output.size() + n > maximum) throw new Exception("Ответ слишком большой"); output.write(block, 0, n); }
            return output.toByteArray();
        }
    }
    private static void checked(HttpsURLConnection c) throws Exception {
        int code = c.getResponseCode();
        if (code < 200 || code >= 300) {
            String message = "Ошибка компьютера (" + code + ")";
            try { message = new JSONObject(new String(read(c.getErrorStream(), 32768), StandardCharsets.UTF_8)).optString("detail", message); } catch (Exception ignored) {}
            throw new ApiException(message);
        }
    }
    private byte[] request(JSONObject config, String path, String method, byte[] body, String contentType) throws Exception {
        return withConnection(config, path, method, c -> {
            if (path.equals("/ping")) { c.setConnectTimeout(2000); c.setReadTimeout(3000); }
            if (body != null) {
                c.setDoOutput(true); c.setRequestProperty("Content-Type", contentType); c.setFixedLengthStreamingMode(body.length);
                c.connect(); // TLS and pin verification happen before the request body is sent.
                try {
                    try (OutputStream out = c.getOutputStream()) { out.write(body); }
                    checked(c); return read(c.getInputStream(), 15 * 1024 * 1024);
                } catch (ApiException e) { throw e; }
                catch (Exception e) { throw new ApiException("Связь прервалась во время запроса. Проверьте результат в WileyAI перед повтором."); }
            }
            checked(c); return read(c.getInputStream(), 15 * 1024 * 1024);
        });
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
        network = null;
        layout(); padded(root, 24);
        TextView heading = text("WileyAI", 30, Color.WHITE); heading.setTypeface(null, Typeface.BOLD); root.addView(heading);
        TextView description = text("Подключение к компьютеру", 19, ACCENT); description.setPadding(0, dp(10), 0, dp(10)); root.addView(description);
        TextView help = text("На компьютере откройте Настройки → Телефон, включите подключение и покажите код. Сканируйте его камерой телефона или вставьте ссылку ниже.", 15, 0xffd5cedf); root.addView(help);
        EditText link = field("wileyai://pair?…"); link.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI | InputType.TYPE_TEXT_FLAG_MULTI_LINE); link.setMinLines(3); link.setText(incoming); root.addView(link);
        Button connect = button("Подключить", () -> {
            if (!link.isEnabled()) return;
            final JSONObject next;
            try { next = parsePair(link.getText().toString()); } catch (Exception e) { error(e.getMessage()); return; }
            new AlertDialog.Builder(this).setTitle("Подключить телефон?").setMessage("Убедитесь, что код показан в вашем WileyAI на компьютере.")
                    .setNegativeButton("Отмена", null).setPositiveButton("Подключить", (d, w) -> {
                        connectButton(false, link);
                        background(() -> {
                            try {
                                JSONObject body = new JSONObject().put("code", next.getString("code")).put("name", Build.MODEL);
                                JSONObject result = new JSONObject(new String(request(next, "/pair", "POST", body.toString().getBytes(StandardCharsets.UTF_8), "application/json"), StandardCharsets.UTF_8));
                                next.remove("code"); next.put("token", result.getString("token")); validateProfile(next, true); saveProfile(next);
                                runOnUiThread(this::showChat);
                            } catch (Exception e) { error(e.getMessage()); runOnUiThread(() -> connectButton(true, link)); }
                        });
                    }).show();
        });
        root.addView(connect);
        if (profile != null) root.addView(button("Вернуться к чату", this::showChat));
        TextView network = text("Через мобильную сеть включите Tailscale на телефоне и компьютере. Компьютер и WileyAI должны работать.", 14, 0xffb8aec7); network.setPadding(0, dp(16), 0, 0); root.addView(network);
    }
    private void connectButton(boolean enabled, EditText input) { input.setEnabled(enabled); }

    private void showChat() {
        if (profile == null) { showPair(""); return; }
        layout();
        LinearLayout header = row(); padded(header, 6); header.setGravity(Gravity.CENTER_VERTICAL);
        title = text("WileyAI", 20, Color.WHITE); title.setTypeface(null, Typeface.BOLD); header.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        network = text("Проверка связи…", 12, ACCENT); header.addView(network);
        header.addView(button("⋮", this::settingsMenu), new LinearLayout.LayoutParams(dp(48), dp(38))); root.addView(header);
        status = text("Новый чат", 12, 0xffc3b3e5); status.setPadding(dp(16), 0, dp(16), dp(2)); root.addView(status);
        LinearLayout nav = row(); padded(nav, 0);
        for (String name : new String[]{"Чаты", "Задачи", "Заметки"}) nav.addView(button(name, () -> { if (name.equals("Чаты")) chooseChat(); else showItems(name.equals("Задачи")); }), new LinearLayout.LayoutParams(0, dp(36), 1));
        Button target = button(phoneTarget ? "Телефон" : "ПК", () -> {});
        target.setOnClickListener(v -> { phoneTarget = !phoneTarget; target.setText(phoneTarget ? "Телефон" : "ПК"); note(phoneTarget ? "Команды выполняются на телефоне" : "Команды выполняются на компьютере"); });
        nav.addView(target, new LinearLayout.LayoutParams(dp(72), dp(36)));
        root.addView(nav);
        scroll = new ScrollView(this); scroll.setFillViewport(true); messages = vertical(); messages.setPadding(dp(16), dp(8), dp(16), dp(12)); scroll.addView(messages);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout bar = row(); padded(bar, 0);
        composer = field("Сообщение Уайли…"); composer.setMaxLines(4); composer.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        bar.addView(composer, new LinearLayout.LayoutParams(0, -2, 1));
        record = button("🎙", this::toggleRecording); bar.addView(record, new LinearLayout.LayoutParams(dp(52), dp(52)));
        send = button("➤", this::send); bar.addView(send, new LinearLayout.LayoutParams(dp(52), dp(52))); root.addView(bar);
        stop = button("Остановить ответ", this::stopChat); stop.setVisibility(View.GONE); root.addView(stop);
        if (!conversation.isEmpty()) background(this::loadMessages);
        ping();
    }
    private void settingsMenu() {
        if (recorder != null) { note("Сначала завершите запись"); return; }
        String[] values = {readAloud ? "Озвучка ответов: включена" : "Озвучка ответов: выключена", "Изменить адрес компьютера", "Подключить другой компьютер", "Забыть подключение"};
        new AlertDialog.Builder(this).setTitle("Телефон").setItems(values, (dialog, which) -> {
            if (which == 0) { readAloud = !readAloud; getSharedPreferences(STORE, MODE_PRIVATE).edit().putBoolean("read_aloud", readAloud).apply(); note(readAloud ? "Озвучка ответов включена" : "Озвучка ответов выключена"); }
            if (which == 1) editAddress();
            if (which == 2) showPair("");
            if (which == 3) new AlertDialog.Builder(this).setMessage("Забыть подключение на телефоне? Его также можно отозвать в настройках WileyAI на компьютере.").setNegativeButton("Отмена", null).setPositiveButton("Забыть", (d, w) -> {
                getSharedPreferences(STORE, MODE_PRIVATE).edit().remove("connection").remove("chat").apply(); profile = null; conversation = ""; showPair("");
            }).show();
        }).show();
    }
    private void editAddress() {
        EditText input = field("Например, 100.101.102.103"); input.setSingleLine(true); input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        new AlertDialog.Builder(this).setTitle("Дополнительный адрес компьютера").setMessage("Укажите адрес из Tailscale, если подключаете телефон через мобильную сеть.").setView(input).setNegativeButton("Отмена", null).setPositiveButton("Сохранить", (d, w) -> {
            String host = input.getText().toString().trim();
            if (!privateIp(host)) { error("Введите IPv4-адрес локальной сети или Tailscale."); return; }
            try {
                JSONArray old = profile.getJSONArray("hosts"), hosts = new JSONArray(); hosts.put(host);
                for (int i = 0; i < old.length() && hosts.length() < 12; i++) if (!host.equals(old.getString(i))) hosts.put(old.getString(i));
                JSONObject replacement = new JSONObject(profile.toString()).put("hosts", hosts); validateProfile(replacement, true); saveProfile(replacement);
                note("Адрес сохранён. Проверяю подключение…"); background(this::loadInitial);
            } catch (Exception e) { error("Не удалось сохранить адрес."); }
        }).show();
    }
    private void loadInitial() {
        ping();
        if (!conversation.isEmpty()) loadMessages();
    }
    private void ping() {
        JSONObject current = profile;
        if (current == null || !pinging.compareAndSet(false, true)) return;
        background(() -> {
            long began = SystemClock.elapsedRealtime();
            try {
                request(current, "/ping", "GET", null, "application/json");
                long elapsed = SystemClock.elapsedRealtime() - began;
                runOnUiThread(() -> { if (network != null && current == profile) network.setText("Связь: " + elapsed + " мс"); });
            } catch (Exception e) { runOnUiThread(() -> { if (network != null && current == profile) network.setText("Нет связи с ПК"); }); }
            finally { pinging.set(false); }
        });
    }
    private void chooseChat() {
        if (recorder != null) { note("Сначала завершите запись"); return; }
        if (chatting.get()) { note("Дождитесь окончания ответа"); return; }
        note("Загружаю чаты…");
        background(() -> {
            try {
                JSONArray chats = new JSONArray(new String(jsonRequest("/conversations", "GET", null), StandardCharsets.UTF_8));
                String[] choices = new String[chats.length() + 1]; choices[0] = "+ Новый чат";
                for (int i = 0; i < chats.length(); i++) choices[i + 1] = chats.getJSONObject(i).optString("title", "Чат");
                runOnUiThread(() -> new AlertDialog.Builder(this).setTitle("Чаты").setItems(choices, (dialog, which) -> background(() -> {
                    try {
                        if (which == 0) { conversation = ""; getSharedPreferences(STORE, MODE_PRIVATE).edit().remove("chat").apply(); runOnUiThread(() -> { messages.removeAllViews(); note("Новый чат"); }); return; }
                        String id = chats.getJSONObject(which - 1).getString("id");
                        conversation = id; getSharedPreferences(STORE, MODE_PRIVATE).edit().putString("chat", id).apply(); loadMessages();
                    } catch (Exception e) { error(e.getMessage()); }
                })).setNegativeButton("Закрыть", null).show());
            } catch (Exception e) { error(e.getMessage()); }
        });
    }
    private void loadMessages() {
        try {
            final String selected = conversation;
            JSONArray list = new JSONArray(new String(jsonRequest("/messages?conversation_id=" + query(selected), "GET", null), StandardCharsets.UTF_8));
            runOnUiThread(() -> {
                if (!selected.equals(conversation) || messages == null) return;
                messages.removeAllViews();
                for (int i = 0; i < list.length(); i++) { JSONObject item = list.optJSONObject(i); if (item != null) addMessage(item.optString("role"), item.optString("content")); }
                note("Подключена к компьютеру"); scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
            });
        } catch (Exception e) { runOnUiThread(() -> note(e.getMessage())); }
    }
    private TextView addMessage(String role, String content) {
        TextView bubble = text(content, 16, Color.WHITE); bubble.setTextIsSelectable(true); bubble.setPadding(dp(14), dp(10), dp(14), dp(10));
        bubble.setBackground(background(role.equals("user") ? 0xff294f82 : CARD, 16));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, 0, 0, dp(8)); messages.addView(bubble, params);
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN)); return bubble;
    }
    private void send() {
        String value = composer.getText().toString().trim();
        if (value.isEmpty() || chatting.get()) return;
        PhoneCommands.Action local = PhoneCommands.parse(value, phoneTarget);
        if (local != null) {
            composer.setText(""); addMessage("user", value); executePhone(local); return;
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
            StringBuilder answer = new StringBuilder(); boolean[] complete = {false};
            try {
                final String selected = ensureConversation();
                JSONObject payload = new JSONObject().put("text", value).put("conversation_id", selected).put("request_id", id)
                        .put("document_ids", new JSONArray()).put("mode", "text").put("timezone", java.util.TimeZone.getDefault().getID());
                byte[] data = payload.toString().getBytes(StandardCharsets.UTF_8);
                withConnection(profile, "/api/chat", "POST", c -> {
                    c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json"); c.setFixedLengthStreamingMode(data.length);
                    c.connect();
                    activeChat = c;
                    try {
                      try (OutputStream out = c.getOutputStream()) { out.write(data); }
                      checked(c);
                      try (BufferedReader reader = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
                        String line; int events = 0;
                        while ((line = reader.readLine()) != null) {
                            if (!line.startsWith("data: ")) continue;
                            if (++events > 100000 || line.length() > 1000000) throw new Exception("Ответ слишком большой");
                            JSONObject event = new JSONObject(line.substring(6)); String type = event.optString("type");
                            if (type.equals("delta")) {
                                answer.append(event.optString("text"));
                                String shown = answer.toString(); runOnUiThread(() -> { if (selected.equals(conversation) && streaming != null) { streaming.setText(shown); scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN)); } });
                            } else if (type.equals("stage")) {
                                String stage = event.optString("text"); boolean noAnswer = answer.length() == 0;
                                runOnUiThread(() -> { note(stage); if (noAnswer && streaming != null) streaming.setText(stage); });
                            }
                            else if (type.equals("done")) { complete[0] = true; JSONObject message = event.optJSONObject("message"); if (message != null) { answer.setLength(0); answer.append(message.optString("content")); } }
                            else if (type.equals("error")) throw new ApiException(event.optString("text", "Не удалось получить ответ"));
                        }
                      }
                      if (!complete[0]) throw new ApiException("Ответ прервался. Проверьте подключение и откройте чат заново.");
                    } catch (ApiException e) { throw e; }
                    catch (Exception e) { throw new ApiException("Ответ прервался. Проверьте подключение и откройте чат заново."); }
                    return null;
                });
                lastAnswer = answer.toString();
                runOnUiThread(() -> { if (selected.equals(conversation) && streaming != null) streaming.setText(lastAnswer); note("Ответ получен"); });
                if (readAloud && !lastAnswer.isEmpty()) speak(lastAnswer);
            } catch (Exception e) { runOnUiThread(() -> { note(e.getMessage()); if (streaming != null && answer.length() == 0) streaming.setText(e.getMessage()); }); }
            finally { activeChat = null; chatting.set(false); requestId = ""; runOnUiThread(() -> { if (send != null) send.setEnabled(true); if (stop != null) stop.setVisibility(View.GONE); }); }
        });
    }
    private void stopChat() {
        String id = requestId; if (id.isEmpty()) return;
        note("Останавливаю ответ…");
        background(() -> { try { jsonRequest("/chat/stop", "POST", new JSONObject().put("request_id", id)); } catch (Exception e) { runOnUiThread(() -> note(e.getMessage())); } });
    }

    private void phoneReply(String message) { addMessage("assistant", message); note("Команда телефона · локально, без сохранения в истории"); }
    private void executePhone(PhoneCommands.Action action) {
        try {
            if (action.kind.equals("volume")) {
                AudioManager audio = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
                int max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                int current = audio.getStreamVolume(AudioManager.STREAM_MUSIC);
                int value = action.value.equals("up") ? Math.min(max, current + Math.max(1, Math.round(max * .1f))) :
                        action.value.equals("down") ? Math.max(0, current - Math.max(1, Math.round(max * .1f))) :
                        action.value.equals("status") ? current : Math.round(max * Integer.parseInt(action.value) / 100f);
                if (!action.value.equals("status")) audio.setStreamVolume(AudioManager.STREAM_MUSIC, value, AudioManager.FLAG_SHOW_UI);
                int actual = audio.getStreamVolume(AudioManager.STREAM_MUSIC);
                phoneReply("Громкость музыки на телефоне: " + (max == 0 ? 0 : Math.round(actual * 100f / max)) + "%."); return;
            }
            if (action.kind.equals("media")) {
                AudioManager audio = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
                int key = action.value.equals("play") ? KeyEvent.KEYCODE_MEDIA_PLAY : action.value.equals("pause") ? KeyEvent.KEYCODE_MEDIA_PAUSE : action.value.equals("next") ? KeyEvent.KEYCODE_MEDIA_NEXT : KeyEvent.KEYCODE_MEDIA_PREVIOUS;
                audio.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, key));
                audio.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, key));
                phoneReply("Команда отправлена медиаплееру телефона. Результат зависит от активного плеера."); return;
            }
            if (action.kind.equals("open")) openPhoneTarget(action.value);
        } catch (Exception e) { phoneReply("Не удалось выполнить команду на телефоне: " + (e.getMessage() == null ? "приложение недоступно" : e.getMessage())); }
    }
    private void openPhoneTarget(String target) throws Exception {
        String key = target.trim().toLowerCase(Locale.ROOT).replace('ё', 'е');
        String url = key.equals("ютуб") || key.equals("youtube") ? "https://www.youtube.com" :
                key.equals("яндекс музыка") ? "" : key.equals("яндекс") ? "https://ya.ru" :
                key.equals("гугл") || key.equals("google") ? "https://www.google.com" :
                key.equals("гитхаб") || key.equals("github") ? "https://github.com" : "";
        if (target.matches("(?i)^https?://[^\\s]+$")) url = target;
        else if (target.matches("(?i)^[a-z0-9-]+(?:\\.[a-z0-9-]+)+(?:/[^\\s]*)?$")) url = "https://" + target;
        if (!url.isEmpty()) {
            Uri uri = Uri.parse(url);
            if (!("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme())) || uri.getHost() == null || uri.getUserInfo() != null) throw new Exception("Допустимы только адреса HTTP и HTTPS");
            startActivity(new Intent(Intent.ACTION_VIEW, uri)); phoneReply("Открываю сайт на телефоне."); return;
        }
        Intent launcher = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> candidates = getPackageManager().queryIntentActivities(launcher, 0);
        List<ResolveInfo> matches = new ArrayList<>();
        for (ResolveInfo candidate : candidates) {
            String label = candidate.loadLabel(getPackageManager()).toString().toLowerCase(Locale.ROOT).replace('ё', 'е').trim();
            if (label.equals(key) || (key.equals("яндекс музыка") && (label.equals("yandex music") || label.equals("яндекс музыка")))) matches.add(candidate);
        }
        if (matches.isEmpty()) { phoneReply("Приложение «" + target + "» не найдено. Назови его так, как оно подписано на телефоне."); return; }
        if (matches.size() == 1) { launchPhoneApp(matches.get(0)); return; }
        String[] names = new String[matches.size()];
        for (int i = 0; i < matches.size(); i++) names[i] = matches.get(i).loadLabel(getPackageManager()) + " (" + matches.get(i).activityInfo.packageName + ")";
        new AlertDialog.Builder(this).setTitle("Какое приложение открыть?").setItems(names, (dialog, index) -> launchPhoneApp(matches.get(index))).setNegativeButton("Отмена", null).show();
    }
    private void launchPhoneApp(ResolveInfo app) {
        try {
            Intent intent = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
            intent.setClassName(app.activityInfo.packageName, app.activityInfo.name); startActivity(intent);
            phoneReply("Открываю «" + app.loadLabel(getPackageManager()) + "» на телефоне.");
        } catch (Exception e) { phoneReply("Не удалось открыть приложение на телефоне."); }
    }

    private void toggleRecording() {
        if (recorder != null) { finishRecording(); return; }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MIC_PERMISSION); return; }
        beginRecording();
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == MIC_PERMISSION && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) beginRecording();
        else if (code == MIC_PERMISSION) note("Разрешите микрофон в настройках Android");
    }
    private void beginRecording() {
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
        background(() -> {
            try {
                byte[] audio = Files.readAllBytes(file.toPath()); if (audio.length > 10 * 1024 * 1024) throw new Exception("Запись слишком длинная");
                String boundary = "wiley" + UUID.randomUUID().toString().replace("-", "");
                ByteArrayOutputStream body = new ByteArrayOutputStream();
                body.write(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n").getBytes(StandardCharsets.UTF_8));
                body.write(audio); body.write(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
                JSONObject result = new JSONObject(new String(request(profile, "/api/voice/transcribe", "POST", body.toByteArray(), "multipart/form-data; boundary=" + boundary), StandardCharsets.UTF_8));
                String recognized = result.optString("text");
                runOnUiThread(() -> { composer.setText(recognized); composer.setSelection(composer.length()); note(recognized.isEmpty() ? "Речь не распознана" : "Проверьте текст и отправьте сообщение"); });
            } catch (Exception e) { runOnUiThread(() -> note(e.getMessage())); }
            finally { file.delete(); }
        });
    }
    private void speak(String value) {
        try {
            byte[] audio = jsonRequest("/voice/synthesize", "POST", new JSONObject().put("text", value));
            File file = File.createTempFile("wiley-answer-", ".audio", getCacheDir()); Files.write(file.toPath(), audio);
            runOnUiThread(() -> {
                releasePlayer(); playback = file;
                try { player = new MediaPlayer(); player.setDataSource(file.getAbsolutePath()); player.setOnCompletionListener(p -> releasePlayer()); player.setOnPreparedListener(MediaPlayer::start); player.prepareAsync(); }
                catch (Exception e) { releasePlayer(); note("Не удалось воспроизвести ответ"); }
            });
        } catch (Exception e) { runOnUiThread(() -> note("Не удалось озвучить ответ: " + e.getMessage())); }
    }
    private void releasePlayer() { if (player != null) { player.release(); player = null; } if (playback != null) { playback.delete(); playback = null; } }

    private void showItems(boolean tasks) {
        if (recorder != null) { note("Сначала завершите запись"); return; }
        note("Загружаю…");
        background(() -> {
            try {
                ensureConversation();
                String endpoint = tasks ? "/tasks" : "/notes";
                JSONArray list = new JSONArray(new String(jsonRequest(endpoint + "?conversation_id=" + query(conversation), "GET", null), StandardCharsets.UTF_8));
                List<String> lines = new ArrayList<>(); lines.add(tasks ? "+ Новая задача" : "+ Новая заметка");
                for (int i = 0; i < list.length(); i++) { JSONObject item = list.getJSONObject(i); lines.add((tasks && taskDone(item) ? "✓ " : "") + item.optString("title", "Без названия")); }
                runOnUiThread(() -> new AlertDialog.Builder(this).setTitle(tasks ? "Задачи" : "Заметки").setItems(lines.toArray(new String[0]), (dialog, which) -> {
                    if (which == 0) createItem(tasks); else {
                        JSONObject item = list.optJSONObject(which - 1); if (item != null) itemDetails(tasks, item);
                    }
                }).setNegativeButton("Закрыть", null).show());
                runOnUiThread(() -> note("Подключена к компьютеру"));
            } catch (Exception e) { runOnUiThread(() -> note(e.getMessage())); }
        });
    }
    private static boolean taskDone(JSONObject item) { return item.optBoolean("done", false) || item.optInt("done", 0) != 0; }
    private void itemDetails(boolean tasks, JSONObject item) {
        AlertDialog.Builder dialog = new AlertDialog.Builder(this).setTitle(item.optString("title"))
                .setMessage(tasks ? (taskDone(item) ? "Выполнена" : "Не выполнена") : item.optString("content"))
                .setPositiveButton("Закрыть", null)
                .setNegativeButton("Удалить", (d, w) -> new AlertDialog.Builder(this).setMessage("Удалить эту запись?").setNegativeButton("Отмена", null).setPositiveButton("Удалить", (confirm, choice) -> background(() -> {
                    try { jsonRequest((tasks ? "/tasks/" : "/notes/") + item.getString("id") + "?conversation_id=" + query(conversation), "DELETE", null); runOnUiThread(() -> note("Запись удалена")); }
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
                runOnUiThread(() -> note("Задача обновлена"));
            } catch (Exception e) { error(e.getMessage()); }
        }));
        dialog.show();
    }
    private void createItem(boolean tasks) {
        LinearLayout form = vertical(); padded(form, 8); EditText name = field(tasks ? "Название задачи" : "Название заметки"); form.addView(name);
        EditText content = field("Текст заметки"); if (!tasks) { content.setMinLines(3); form.addView(content); }
        new AlertDialog.Builder(this).setTitle(tasks ? "Новая задача" : "Новая заметка").setView(form).setNegativeButton("Отмена", null).setPositiveButton("Создать", (d, w) -> {
            String titleValue = name.getText().toString(), contentValue = content.getText().toString();
            background(() -> {
            try {
                JSONObject body = new JSONObject().put("title", titleValue).put(tasks ? "kind" : "content", tasks ? "todo" : contentValue);
                jsonRequest((tasks ? "/tasks" : "/notes") + "?conversation_id=" + query(conversation), "POST", body);
                runOnUiThread(() -> note(tasks ? "Задача создана" : "Заметка создана"));
            } catch (Exception e) { error(e.getMessage()); }
            });
        }).show();
    }
}
