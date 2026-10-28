import ru.wildlik.wileyai.mobile.PinnedTls;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLException;

/** Runs the same pure Java TLS implementation used by Android against the real gateway. */
public final class PinProbe {
    private static String send(String host, String pin, String path, String method, String token, String body) throws Exception {
        HttpsURLConnection connection = PinnedTls.open(host, 48443, pin, path, method, token);
        try {
            if (body != null) {
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json"); connection.setFixedLengthStreamingMode(bytes.length);
                connection.connect();
                try (OutputStream output = connection.getOutputStream()) { output.write(bytes); }
            }
            if (connection.getResponseCode() != 200) throw new Exception("HTTP " + connection.getResponseCode());
            try (InputStream input = connection.getInputStream()) { return new String(input.readAllBytes(), StandardCharsets.UTF_8); }
        } finally { connection.disconnect(); }
    }
    public static void main(String[] args) throws Exception {
        String host = args[0], pin = args[1], code = args[2];
        String bad = (pin.startsWith("0") ? "1" : "0") + pin.substring(1);
        try { send(host, bad, "/pair", "POST", "", "{\"code\":\"" + code + "\"}"); throw new Exception("Wrong fingerprint was accepted"); }
        catch (SSLException expected) { /* no pairing credential was sent */ }
        String result = send(host, pin, "/pair", "POST", "", "{\"code\":\"" + code + "\",\"name\":\"Android test\"}");
        Matcher match = Pattern.compile("\\\"token\\\":\\\"([A-Za-z0-9_-]+)\\\"").matcher(result);
        if (!match.find()) throw new Exception("Pairing returned no token");
        String token = match.group(1);
        if (!send(host, pin, "/api/conversations", "GET", token, null).contains("fixture")) throw new Exception("Conversation unavailable");
        if (!send(host, pin, "/api/chat", "POST", token, "{\"text\":\"hello\"}").contains("done")) throw new Exception("Chat stream unavailable");
        if (PinnedTls.privateIp("8.8.8.8", false) || !PinnedTls.privateIp("100.64.2.3", false) || PinnedTls.privateIp("127.0.0.1", false)) throw new Exception("Address validation failed");
        System.out.println("Android Java TLS: correct certificate accepted, wrong certificate rejected, pairing and chat passed");
    }
}
