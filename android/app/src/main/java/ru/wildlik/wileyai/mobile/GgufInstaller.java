package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

/** Validates a catalogued single-file model before an atomic pointer swap. No Android dependency. */
public final class GgufInstaller {
    public interface Validator { void validate(Path file) throws Exception; }
    public interface Progress { void phase(String phase); }
    private static void check(AtomicBoolean cancel) throws InterruptedIOException { if (cancel.get()) throw new InterruptedIOException("Установка остановлена"); }
    public static Path active(Path base, long expected) throws IOException {
        Path pointer = base.resolve("active"); if (!Files.exists(pointer)) return null;
        if (Files.size(pointer) > 80) throw new IOException("Повреждён указатель LLM");
        String name = new String(Files.readAllBytes(pointer), StandardCharsets.US_ASCII).trim();
        if (!name.matches("model-[a-f0-9]{32}\\.gguf")) throw new IOException("Повреждён указатель LLM");
        Path model = base.resolve(name); if (!Files.isRegularFile(model) || Files.size(model) != expected) throw new IOException("Файл LLM не найден или повреждён"); return model;
    }
    public static Path install(Path base, Path part, long bytes, String sha256, AtomicBoolean cancel, Validator validator, Progress progress) throws Exception {
        if (bytes < 8 || !sha256.matches("[a-f0-9]{64}")) throw new IOException("Некорректный каталог GGUF");
        check(cancel); if (Files.size(part) != bytes) throw new IOException("Размер GGUF не совпал с каталогом");
        progress.phase("Проверяю SHA-256…"); MessageDigest digest = MessageDigest.getInstance("SHA-256"); byte[] block = new byte[65536];
        try (InputStream input = Files.newInputStream(part)) { int n; while ((n = input.read(block)) != -1) { check(cancel); digest.update(block, 0, n); } }
        if (!VerifiedModelInstaller.hex(digest.digest()).equals(sha256)) throw new IOException("Контрольная сумма GGUF не совпала. Сбросьте незавершённую загрузку и повторите.");
        try (InputStream input = Files.newInputStream(part)) { if (input.read() != 'G' || input.read() != 'G' || input.read() != 'U' || input.read() != 'F') throw new IOException("Выбранный файл не является GGUF"); }
        check(cancel); progress.phase("Проверяю загрузку движком…"); validator.validate(part); check(cancel);
        Files.createDirectories(base); Path generation = base.resolve("model-" + UUID.randomUUID().toString().replace("-", "") + ".gguf"); Path next = base.resolve("next"); boolean published = false;
        try {
            Files.move(part, generation, StandardCopyOption.ATOMIC_MOVE);
            try (FileOutputStream output = new FileOutputStream(next.toFile())) { output.write(generation.getFileName().toString().getBytes(StandardCharsets.US_ASCII)); output.getFD().sync(); }
            progress.phase("Сохраняю модель…"); check(cancel);
            Files.move(next, base.resolve("active"), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); published = true; return generation;
        } finally {
            Files.deleteIfExists(next);
            if (!published && Files.exists(generation)) Files.move(generation, part, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        }
    }
    private GgufInstaller() {}
}
