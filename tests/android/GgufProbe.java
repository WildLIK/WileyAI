import ru.wildlik.wileyai.mobile.GgufInstaller;
import ru.wildlik.wileyai.mobile.VerifiedModelInstaller;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;

public final class GgufProbe {
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static String sha(byte[] data) throws Exception { return VerifiedModelInstaller.hex(MessageDigest.getInstance("SHA-256").digest(data)); }
    public static void main(String[] args) throws Exception {
        String scenario = args[0]; Path base = Paths.get(args[1]); Files.createDirectories(base);
        byte[] first = "GGUF-first-test-file".getBytes(), second = "GGUF-other-test-file".getBytes(); Path part = base.resolve("test.part"); Files.write(part, first);
        Path old = GgufInstaller.install(base, part, first.length, sha(first), new AtomicBoolean(), p -> {}, phase -> {});
        check(GgufInstaller.active(base, first.length).equals(old)); Files.write(part, second); AtomicBoolean cancel = new AtomicBoolean();
        boolean failed = false;
        if (scenario.equals("invalid-pointer")) { Files.write(base.resolve("active"), "../secret".getBytes()); try { GgufInstaller.active(base, first.length); } catch (java.io.IOException expected) { failed = true; } check(failed && Files.exists(old)); }
        else {
            try {
                long bytes = scenario.equals("short-file") ? second.length + 1 : second.length;
                String digest = scenario.equals("bad-sha") ? "0".repeat(64) : sha(second);
                Path installed = GgufInstaller.install(base, part, bytes, digest, cancel, p -> { if (scenario.equals("engine-failure")) throw new java.io.IOException("native reject"); if (scenario.equals("cancel-after-validation")) cancel.set(true); }, phase -> { if (scenario.equals("cancel-before-publication") && phase.startsWith("Сохраняю")) cancel.set(true); });
                check(scenario.equals("replace")); check(Arrays.equals(Files.readAllBytes(installed), second)); check(!installed.equals(old)); check(Files.exists(old));
            } catch (java.io.IOException expected) { failed = true; }
            if (!scenario.equals("replace")) { check(failed); check(GgufInstaller.active(base, first.length).equals(old)); check(Arrays.equals(Files.readAllBytes(old), first)); check(Files.exists(part)); }
        }
        System.out.println("passed: " + scenario);
    }
}
