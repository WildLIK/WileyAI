package ru.wildlik.wileyai.mobile;

import android.content.Context;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.Locale;

/** Extracts and SHA-256-verifies bundled Stage 1 wakeword and speaker models into noBackupFilesDir. */
final class WakeModelAssets {
    static final String C_V2_ASSET = "wake-stage1/C_v2.onnx";
    static final String C_V2_SHA256 = "f1f42392a4dbeac6519db01d30340ccf44c353ebaf009a5fb5ad17ca891fb54d";
    static final String CAMPPLUS_ASSET = "wake-stage1/campplus.onnx";
    static final String CAMPPLUS_SHA256 = "53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b";

    static Path ensureLiveKitV2(Context context) throws IOException {
        return ensureVerified(context, C_V2_ASSET, "C_v2.onnx", C_V2_SHA256);
    }

    static Path ensureCamPlus(Context context) throws IOException {
        return ensureVerified(context, CAMPPLUS_ASSET, "campplus.onnx", CAMPPLUS_SHA256);
    }

    static boolean hasLiveKit(Context context) { return bundled(context, "C_v2.onnx"); }

    static boolean hasCamPlus(Context context) { return bundled(context, "campplus.onnx"); }

    static boolean liveKitEligible(Context context, int engine, String phrase) {
        return engine != WakeSettings.ENGINE_VOSK && hasLiveKit(context)
                && (WakePhrase.SHORT.equals(phrase) || WakePhrase.DEFAULT.equals(phrase))
                && (engine != WakeSettings.ENGINE_LIVEKIT_V2_CAM
                    || (hasCamPlus(context) && OwnerSpeakerFilter.hasEnrolledProfile(context)));
    }

    private static boolean bundled(Context context, String name) {
        try {
            String[] entries = context.getAssets().list("wake-stage1");
            return entries != null && java.util.Arrays.asList(entries).contains(name);
        } catch (IOException absent) { return false; }
    }

    private static synchronized Path ensureVerified(
            Context context, String assetPath, String fileName, String expectedSha256) throws IOException {
        Context app = context.getApplicationContext();
        Path dir = app.getNoBackupFilesDir().toPath().resolve("wake-stage1");
        Files.createDirectories(dir);
        Path target = dir.resolve(fileName);
        if (Files.isRegularFile(target) && expectedSha256.equals(sha256(target))) {
            return target;
        }
        Path part = Files.createTempFile(dir, fileName, ".part");
        try (InputStream in = app.getAssets().open(assetPath)) {
            Files.copy(in, part, StandardCopyOption.REPLACE_EXISTING);
            String actual = sha256(part);
            if (!expectedSha256.equals(actual)) {
                throw new IOException("Не совпала контрольная сумма модели " + fileName);
            }
            Files.move(part, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            return target;
        } finally {
            Files.deleteIfExists(part);
        }
    }

    private static String sha256(Path file) throws IOException {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[32768];
            try (InputStream in = Files.newInputStream(file)) {
                for (int n; (n = in.read(buf)) != -1; ) md.update(buf, 0, n);
            }
            StringBuilder hex = new StringBuilder(64);
            for (byte b : md.digest()) hex.append(String.format(Locale.ROOT, "%02x", b));
            return hex.toString();
        } catch (Exception e) {
            throw new IOException("Ошибка расчёта SHA-256 для " + file.getFileName(), e);
        }
    }

    private WakeModelAssets() {}
}
