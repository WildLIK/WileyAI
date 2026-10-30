package ru.wildlik.wileyai.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLException;
import java.security.cert.CertificateException;

/** Pinned PC transport. Never retries a request after its body may have been sent. */
final class PcGateway {
    private volatile String lastWorkingHost = "";
    volatile HttpsURLConnection activeChat;
    private HttpsURLConnection open(JSONObject config, String host, String path, String method) throws Exception {
        if (!SettingsRepository.privateIp(host)) throw new Exception("Недопустимый адрес");
        return PinnedTls.open(host, config.getInt("port"), config.getString("fingerprint"), path, method, config.optString("token", ""));
    }
    interface ConnectionWork<T> { T run(HttpsURLConnection connection) throws Exception; }
    <T> T withConnection(JSONObject config, String path, String method, ConnectionWork<T> work) throws Exception {
        SettingsRepository.validateProfile(config, !path.equals("/pair"));
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
    static final class ApiException extends Exception { ApiException(String message) { super(message); } }
    static byte[] read(InputStream input, int maximum) throws Exception {
        try (InputStream source = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] block = new byte[8192]; int n;
            while ((n = source.read(block)) != -1) { if (output.size() + n > maximum) throw new Exception("Ответ слишком большой"); output.write(block, 0, n); }
            return output.toByteArray();
        }
    }
    static void checked(HttpsURLConnection c) throws Exception {
        int code = c.getResponseCode();
        if (code < 200 || code >= 300) {
            String message = "Ошибка компьютера (" + code + ")";
            try { message = new JSONObject(new String(read(c.getErrorStream(), 32768), StandardCharsets.UTF_8)).optString("detail", message); } catch (Exception ignored) {}
            throw new ApiException(message);
        }
    }
    byte[] request(JSONObject config, String path, String method, byte[] body, String contentType) throws Exception {
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
    interface StreamListener {
        void delta(String value);
        void stage(String value);
        void done(String value);
        default void speechMode(String mode, String preference) {}
        default void speechResult(String spoken) {}
    }
    void stream(JSONObject config, byte[] data, StreamListener listener) throws Exception {
        withConnection(config, "/api/chat", "POST", c -> {
            c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json"); c.setFixedLengthStreamingMode(data.length);
            c.connect(); activeChat = c;
            try {
                try (OutputStream out = c.getOutputStream()) { out.write(data); }
                checked(c); boolean complete = false; int events = 0, characters = 0;
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (!line.startsWith("data: ")) continue;
                        if (++events > 100000 || line.length() > 1000000 || (characters += line.length()) > 15 * 1024 * 1024) throw new ApiException("Ответ слишком большой");
                        JSONObject event = new JSONObject(line.substring(6));
                        switch (event.optString("type")) {
                            case "delta": listener.delta(event.optString("text")); break;
                            case "stage": listener.stage(event.optString("text")); break;
                            case "speech_mode": listener.speechMode(event.optString("mode"), event.optString("preference", "brief")); break;
                            case "speech_result": JSONObject action = event.optJSONObject("action"); listener.speechResult(action == null ? "" : action.optString("spoken")); break;
                            case "done":
                                complete = true; JSONObject message = event.optJSONObject("message");
                                listener.done(message == null ? null : message.optString("content")); break;
                            case "error": throw new ApiException(event.optString("text", "Не удалось получить ответ"));
                        }
                    }
                }
                if (!complete) throw new ApiException("Ответ прервался. Проверьте подключение и откройте чат заново.");
            } catch (ApiException e) { throw e; }
            catch (Exception e) { throw new ApiException("Ответ прервался. Проверьте результат на компьютере перед повтором."); }
            finally { activeChat = null; }
            return null;
        });
    }
}
