package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.Build;
import android.os.SystemClock;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
import java.util.function.IntConsumer;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONObject;

/** The operation lock is shared by the foreground panel and the automatic check job. */
final class ReleaseUpdates {
    static final String PAGE = "https://github.com/WildLIK/WileyAI/releases";
    static final String OPEN = BuildConfig.APPLICATION_ID + ".SHOW_UPDATE";
    private static final String CATALOG = "https://api.github.com/repos/WildLIK/WileyAI/releases/latest";
    private static final String MANIFEST = "wiley-update-v2.json";
    private static final String NAME = "[A-Za-z0-9][A-Za-z0-9._-]{0,119}";
    private static final Set<String> ASSET_HOSTS = new HashSet<>(java.util.Arrays.asList(
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"));
    private static final long MAX_APK = 2L * 1024 * 1024 * 1024;
    private static final long CHECK_INTERVAL = 6 * 3600_000L;
    private static volatile State state = new State(null, false, "", 0);
    private static final java.util.concurrent.Executor WORK = java.util.concurrent.Executors.newSingleThreadExecutor();
    static void run(Runnable work) { WORK.execute(work); }
    record State(Offer offer, boolean ready, String error, long checkedAt) {}
    record Offer(String url, String version, long code, long size, String sha, String signer, String notes, String date) {}

    static android.content.SharedPreferences preferences(Context context) {
        return context.getSharedPreferences("release-updates", Context.MODE_PRIVATE);
    }
    static boolean enabled(Context context) { return preferences(context).getBoolean("automatic", true); }
    static boolean configured() { return !BuildConfig.UPDATE_PUBLIC_KEY.isEmpty(); }
    static State state() { return state; }
    static File file(Context context) { return new File(context.getCacheDir(), "WileyAI-Update.apk"); }
    static synchronized void check(Context context, boolean manual) {
        long now = System.currentTimeMillis();
        var prefs = preferences(context);
        if (!manual && (!configured() || !enabled(context)
                || (!prefs.contains("channel") && state.checkedAt() > 0
                && now - prefs.getLong("last_check", 0) < CHECK_INTERVAL))) return;
        State previous = state;
        try {
            if (!configured()) throw new IllegalArgumentException("В этой сборке нет доверенного ключа обновлений.");
            Offer offer = find(context);
            boolean ready = offer != null && offer.equals(previous.offer()) && previous.ready();
            state = new State(offer, ready, "", now);
            if (offer != null && enabled(context)) notifyAvailable(context, offer);
        } catch (IllegalArgumentException error) {
            state = new State(null, false, error.getMessage(), now);
        } catch (Exception error) {
            state = new State(null, false, "Не удалось проверить выпуск. Проверьте интернет и повторите попытку.", now);
        } finally {
            prefs.edit().remove("channel").putLong("last_check", now).apply();
        }
    }

    private static Offer find(Context context) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + 60_000;
        JSONObject release = new JSONObject(read(CATALOG, true, deadline));
        if (release.optBoolean("draft") || release.optBoolean("prerelease")) return null;
        String tag = release.getString("tag_name");
        if (!tag.matches("v(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})")) {
            throw new IllegalArgumentException("Недопустимая метка выпуска.");
        }
        if (!newer(tag.substring(1), BuildConfig.VERSION_NAME)) return null;
        Set<String> names = new HashSet<>();
        JSONArray assets = release.getJSONArray("assets");
        for (int j = 0; j < assets.length(); j++) names.add(assets.getJSONObject(j).getString("name"));
        if (!names.contains(MANIFEST)) throw new IllegalArgumentException("У последнего выпуска нет подписанного манифеста обновления.");
        String base = PAGE + "/download/" + tag + "/";
        JSONObject manifest = verify(new JSONObject(read(base + MANIFEST, false, deadline)), tag);
        JSONArray items = manifest.getJSONArray("artifacts");
        JSONObject apk = null;
        for (int j = 0; j < items.length(); j++) {
            JSONObject item = items.getJSONObject(j);
            if (!"android".equals(item.getString("platform")) || !"universal".equals(item.getString("arch"))) continue;
            if (apk != null) throw new IllegalArgumentException("В выпуске несколько универсальных APK.");
            apk = item;
        }
        if (apk == null) throw new IllegalArgumentException("В выпуске нет универсального APK.");
        String name = apk.getString("name"), version = apk.getString("version");
        String signer = apk.getString("signer_sha256"), sha = apk.getString("sha256");
        long size = apk.getLong("size"), code = apk.getLong("version_code");
        if (!context.getPackageName().equals(apk.getString("package_id")) || !name.matches(NAME)
                || !name.endsWith(".apk") || !names.contains(name) || !tag.equals("v" + version)
                || !sha.matches("[0-9a-f]{64}") || !signer.matches("[0-9a-f]{64}")
                || size < 1 || size > MAX_APK || code < 1) {
            throw new IllegalArgumentException("Манифест содержит несовместимый APK.");
        }
        if (code <= BuildConfig.VERSION_CODE) return null;
        if (!installedSigner(context).equals(signer)) {
            throw new IllegalArgumentException("Подпись выпуска не подходит к установленной WileyAI.");
        }
        return new Offer(base + name, version, code, size, sha, signer, manifest.getString("notes"), manifest.optString("date"));
    }

    private static boolean newer(String published, String installed) {
        String[] target = published.split("\\."), current = installed.split("\\.");
        for (int i = 0; i < 3; i++) {
            int comparison = Integer.compare(Integer.parseInt(target[i]), Integer.parseInt(current[i]));
            if (comparison != 0) return comparison > 0;
        }
        return false;
    }

    private static JSONObject verify(JSONObject envelope, String tag) {
        try {
            byte[] payload = UpdateSignature.verify(BuildConfig.UPDATE_PUBLIC_KEY, envelope.getString("payload"), envelope.getString("signature"));
            JSONObject manifest = new JSONObject(new String(payload, StandardCharsets.UTF_8));
            if (manifest.getInt("schema") != 2 || !tag.equals(manifest.getString("tag")) || manifest.getString("notes").length() > 8000
                    || manifest.getJSONArray("artifacts").length() > 8) throw new IOException();
            return manifest;
        } catch (Exception error) {
            throw new IllegalArgumentException("Подпись или формат манифеста выпуска не прошли проверку.");
        }
    }

    private static void notifyAvailable(Context context, Offer offer) {
        var prefs = preferences(context);
        if (offer.code() <= prefs.getLong("last_notified_code", 0)) return;
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) return;
        var manager = context.getSystemService(android.app.NotificationManager.class);
        if (manager == null || !manager.areNotificationsEnabled()) return;
        try {
            String id = "app-updates";
            manager.createNotificationChannel(new android.app.NotificationChannel(id, "Обновления WileyAI",
                    android.app.NotificationManager.IMPORTANCE_DEFAULT));
            var launch = new android.content.Intent(context, MainActivity.class).setAction(OPEN)
                    .addFlags(android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP | android.content.Intent.FLAG_ACTIVITY_CLEAR_TOP);
            var open = android.app.PendingIntent.getActivity(context, 681, launch,
                    android.app.PendingIntent.FLAG_IMMUTABLE | android.app.PendingIntent.FLAG_UPDATE_CURRENT);
            manager.notify(681, new android.app.Notification.Builder(context, id)
                    .setSmallIcon(R.drawable.nav_settings).setContentTitle("Доступна WileyAI " + offer.version())
                    .setContentText("Откройте приложение, чтобы посмотреть изменения и установить обновление.")
                    .setContentIntent(open).setAutoCancel(true).build());
            prefs.edit().putLong("last_notified_code", offer.code()).apply();
        } catch (SecurityException unavailable) {
            // The offer remains visible in About if notifications are disabled.
        }
    }

    private static HttpsURLConnection connect(String address, boolean api, long deadline) throws IOException {
        URL url = new URL(address);
        for (int attempt = 0; attempt < 5; attempt++) {
            if (SystemClock.elapsedRealtime() >= deadline) throw new IOException("deadline");
            if (!"https".equals(url.getProtocol()) || !(api ? "api.github.com".equals(url.getHost()) : ASSET_HOSTS.contains(url.getHost()))
                    || url.getUserInfo() != null || (url.getPort() != -1 && url.getPort() != 443)) {
                throw new IllegalArgumentException("Недопустимый адрес загрузки выпуска.");
            }
            HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
            boolean accepted = false;
            try {
                connection.setConnectTimeout(12000);
                connection.setReadTimeout(12000);
                connection.setInstanceFollowRedirects(false);
                connection.setRequestProperty("User-Agent", "WileyAI-Updater");
                connection.setRequestProperty("Accept-Encoding", "identity");
                int code = connection.getResponseCode();
                if (code == 200) { accepted = true; return connection; }
                String location = connection.getHeaderField("Location");
                if (api || location == null || !(code == 301 || code == 302 || code == 303 || code == 307 || code == 308)) {
                    throw new IOException("http");
                }
                url = new URL(url, location);
            } finally {
                if (!accepted) connection.disconnect();
            }
        }
        throw new IOException("redirect limit");
    }

    private static String read(String url, boolean api, long deadline) throws IOException {
        var connection = connect(url, api, deadline);
        try (var input = connection.getInputStream(); var output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16384];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > 1024 * 1024 || SystemClock.elapsedRealtime() >= deadline) throw new IOException("metadata limit");
                output.write(buffer, 0, count);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        } finally { connection.disconnect(); }
    }

    static synchronized void download(Context context, Offer expected, IntConsumer progress) throws Exception {
        State current = state;
        if (expected == null || !expected.equals(current.offer())) throw new IllegalArgumentException("Повторите проверку обновлений.");
        File file = file(context);
        if (verified(context, file, expected)) {
            state = new State(expected, true, "", current.checkedAt());
            return;
        }
        state = new State(expected, false, "", current.checkedAt());
        File part = new File(context.getCacheDir(), "WileyAI-Update-partial.apk");
        Files.deleteIfExists(part.toPath());
        if (part.getParentFile().getUsableSpace() < expected.size() + 16L * 1024 * 1024) {
            throw new IllegalArgumentException("Недостаточно свободного места для загрузки.");
        }
        long deadline = SystemClock.elapsedRealtime() + 30 * 60_000L;
        var connection = connect(expected.url(), false, deadline);
        try {
            try (var input = connection.getInputStream(); var output = Files.newOutputStream(part.toPath())) {
                byte[] buffer = new byte[65536];
                long total = 0;
                int count, lastPercent = -1;
                while ((count = input.read(buffer)) != -1) {
                    total += count;
                    if (total > expected.size() || SystemClock.elapsedRealtime() >= deadline) throw new IOException("download limit");
                    output.write(buffer, 0, count);
                    int percent = (int) (100 * total / expected.size());
                    if (percent != lastPercent) { progress.accept(percent); lastPercent = percent; }
                }
            }
            if (!verified(context, part, expected)) throw new IllegalArgumentException("APK повреждён или несовместим.");
            Files.move(part.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            state = new State(expected, true, "", current.checkedAt());
        } finally {
            connection.disconnect();
            Files.deleteIfExists(part.toPath());
        }
    }

    static synchronized boolean prepareInstall(Context context, Offer offer) throws Exception {
        if (offer == null || !offer.equals(state.offer())) return false;
        boolean valid = verified(context, file(context), offer);
        if (!valid) state = new State(offer, false, "", state.checkedAt());
        return valid;
    }

    @SuppressWarnings("deprecation")
    private static int signingFlags() {
        return Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
    }
    @SuppressWarnings("deprecation")
    private static long code(PackageInfo pkg) {
        return Build.VERSION.SDK_INT >= 28 ? pkg.getLongVersionCode() : pkg.versionCode;
    }
    @SuppressWarnings("deprecation")
    private static String signer(PackageInfo pkg) throws Exception {
        Signature[] signatures = Build.VERSION.SDK_INT >= 28
                ? (pkg.signingInfo == null ? null : pkg.signingInfo.getApkContentsSigners()) : pkg.signatures;
        return signatures == null || signatures.length != 1 ? "" :
                hex(MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray()));
    }
    private static String installedSigner(Context context) throws Exception {
        return signer(context.getPackageManager().getPackageInfo(context.getPackageName(), signingFlags()));
    }
    private static boolean verified(Context context, File file, Offer offer) throws Exception {
        if (file.length() != offer.size()) return false;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[65536];
        try (InputStream input = Files.newInputStream(file.toPath())) {
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        if (!offer.sha().equals(hex(digest.digest()))) return false;
        PackageInfo apk = context.getPackageManager().getPackageArchiveInfo(file.getPath(), signingFlags());
        return apk != null && context.getPackageName().equals(apk.packageName) && code(apk) == offer.code()
                && code(apk) > BuildConfig.VERSION_CODE && offer.version().equals(apk.versionName)
                && offer.signer().equals(signer(apk)) && offer.signer().equals(installedSigner(context));
    }
    private static String hex(byte[] digest) {
        StringBuilder result = new StringBuilder(2 * digest.length);
        for (byte value : digest) result.append(Character.forDigit((value & 255) >> 4, 16)).append(Character.forDigit(value & 15, 16));
        return result.toString();
    }
}
