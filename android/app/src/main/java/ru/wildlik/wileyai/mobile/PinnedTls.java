package ru.wildlik.wileyai.mobile;

import java.net.URL;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** HTTPS whose server identity is the certificate shown by WileyAI during pairing. */
public final class PinnedTls {
    private PinnedTls() {}

    public static boolean privateIp(String host, boolean allowLoopback) {
        if (host == null || !host.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}")) return false;
        String[] p = host.split("\\."); int[] b = new int[4];
        for (int i = 0; i < 4; i++) { b[i] = Integer.parseInt(p[i]); if (b[i] > 255 || (p[i].length() > 1 && p[i].startsWith("0"))) return false; }
        return (allowLoopback && b[0] == 127) || b[0] == 10 || (b[0] == 172 && b[1] >= 16 && b[1] <= 31) || (b[0] == 192 && b[1] == 168) || (b[0] == 100 && b[1] >= 64 && b[1] <= 127);
    }

    public static HttpsURLConnection open(String host, int port, String fingerprint, String path, String method, String token) throws Exception {
        if (!privateIp(host, true) || port != 48443 || !fingerprint.matches("[a-f0-9]{64}") || !path.startsWith("/") || path.startsWith("//") || path.contains("\n") || path.contains("\r")) throw new Exception("Недопустимый адрес");
        byte[] expected = new byte[32];
        for (int i = 0; i < expected.length; i++) expected[i] = (byte) Integer.parseInt(fingerprint.substring(i * 2, i * 2 + 2), 16);
        X509TrustManager trust = new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            public void checkClientTrusted(X509Certificate[] chain, String type) throws CertificateException { throw new CertificateException("client certificate not expected"); }
            public void checkServerTrusted(X509Certificate[] chain, String type) throws CertificateException {
                try {
                    if (chain == null || chain.length == 0 || !MessageDigest.isEqual(expected, MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded())))
                        throw new CertificateException("Сертификат компьютера не совпадает");
                    chain[0].checkValidity();
                } catch (CertificateException e) { throw e; }
                catch (Exception e) { throw new CertificateException("Не удалось проверить сертификат"); }
            }
        };
        SSLContext context = SSLContext.getInstance("TLS"); context.init(null, new TrustManager[]{trust}, new SecureRandom());
        HttpsURLConnection conn = (HttpsURLConnection) new URL("https://" + host + ":" + port + path).openConnection();
        conn.setSSLSocketFactory(context.getSocketFactory());
        conn.setHostnameVerifier((hostname, session) -> hostname.equals(host)); // A matching certificate pin is required above.
        conn.setInstanceFollowRedirects(false); conn.setConnectTimeout(5000); conn.setReadTimeout(180000); conn.setRequestMethod(method);
        conn.setRequestProperty("Accept", "application/json, text/event-stream");
        if (token != null && !token.isEmpty()) conn.setRequestProperty("Authorization", "Bearer " + token);
        return conn;
    }
}
