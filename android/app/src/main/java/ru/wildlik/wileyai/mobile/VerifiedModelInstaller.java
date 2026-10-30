package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** Bounded extraction and atomic publication; contains no Android or networking code. */
public final class VerifiedModelInstaller {
    public record Spec(String id, long bytes, String sha256, String md5, long maxExpanded) {}
    public interface Validator { void validate(Path model) throws Exception; }
    public interface Progress { void report(String phase, long done, long total); }
    public static final class ChecksumException extends IOException {
        ChecksumException() { super("Контрольная сумма модели не совпала. Повторите загрузку или выберите официальный ZIP."); }
    }
    private VerifiedModelInstaller() {}
    private static void check(AtomicBoolean cancel) throws InterruptedIOException {
        if (cancel.get() || Thread.currentThread().isInterrupted()) throw new InterruptedIOException("Операция остановлена");
    }
    public static Path active(Path base) throws IOException {
        Path pointer = base.resolve("active");
        if (!Files.exists(pointer)) return null;
        if (Files.size(pointer) > 100) throw new IOException("Повреждён указатель голосовой модели");
        String id = new String(Files.readAllBytes(pointer), StandardCharsets.US_ASCII).trim();
        if (!id.matches("generation-[a-f0-9]{32}")) throw new IOException("Повреждён указатель голосовой модели");
        Path generation = base.resolve(id);
        if (!Files.isDirectory(generation) || !Files.isRegularFile(generation.resolve(".validated"))) throw new IOException("Не найдена проверенная голосовая модель");
        Path marker = generation.resolve(".validated");
        if (Files.size(marker) != 64 || !new String(Files.readAllBytes(marker), StandardCharsets.US_ASCII).matches("[a-f0-9]{64}")) throw new IOException("Повреждена запись проверки речевой модели");
        return generation;
    }
    public static Path install(Path base, Path archive, Spec spec, AtomicBoolean cancel, Progress progress, Validator validator) throws Exception {
        if (!spec.id().matches("[a-z0-9][a-z0-9._-]{1,99}") || !spec.sha256().matches("[a-f0-9]{64}") || !spec.md5().matches("[a-f0-9]{32}") || spec.bytes() < 1 || spec.maxExpanded() < 1) throw new IOException("Некорректные метаданные модели");
        Files.createDirectories(base);
        if (Files.size(archive) != spec.bytes()) throw new IOException("Размер архива не совпадает с каталогом");
        MessageDigest sha = MessageDigest.getInstance("SHA-256"), md5 = MessageDigest.getInstance("MD5");
        long read = 0; byte[] block = new byte[65536];
        try (InputStream input = Files.newInputStream(archive)) {
            int n; while ((n = input.read(block)) != -1) { check(cancel); sha.update(block, 0, n); md5.update(block, 0, n); read += n; progress.report("Проверка SHA-256", read, spec.bytes()); }
        }
        if (!hex(sha.digest()).equals(spec.sha256()) || !hex(md5.digest()).equals(spec.md5())) throw new ChecksumException();
        String suffix = UUID.randomUUID().toString().replace("-", "");
        Path stage = base.resolve("staging-" + suffix), generation = base.resolve("generation-" + suffix), next = base.resolve("pointer-" + suffix);
        boolean published = false;
        try {
            Files.createDirectory(stage);
            long expanded = 0; int files = 0; Set<String> seen = new HashSet<>();
            try (ZipInputStream zip = new ZipInputStream(Files.newInputStream(archive))) {
                ZipEntry entry;
                while ((entry = zip.getNextEntry()) != null) {
                    check(cancel);
                    String name = entry.getName();
                    if (++files > 2048 || name.indexOf('\\') >= 0 || name.indexOf(':') >= 0 || name.startsWith("/") || name.length() > 500 || Arrays.asList(name.split("/")).contains("..")) throw new IOException("Недопустимый путь в архиве модели");
                    String root = spec.id() + "/";
                    if (!name.startsWith(root)) throw new IOException("Архив содержит другую модель");
                    String relative = name.substring(root.length()); if (relative.isEmpty() && entry.isDirectory()) continue;
                    if (relative.equals(".validated") || !seen.add(relative)) throw new IOException("Повторяющийся файл в архиве модели");
                    Path target = stage.resolve(relative).normalize();
                    if (!target.startsWith(stage) || target.equals(stage)) throw new IOException("Недопустимый путь в архиве модели");
                    if (entry.isDirectory()) { Files.createDirectories(target); continue; }
                    Files.createDirectories(target.getParent());
                    try (OutputStream output = Files.newOutputStream(target, StandardOpenOption.CREATE_NEW)) {
                        int n; while ((n = zip.read(block)) != -1) {
                            check(cancel); expanded += n;
                            if (expanded > spec.maxExpanded()) throw new IOException("Распакованный архив превышает допустимый размер");
                            output.write(block, 0, n); progress.report("Распаковка", expanded, 0);
                        }
                    }
                }
            }
            check(cancel); progress.report("Пробная загрузка движка", 0, 0); validator.validate(stage); check(cancel);
            Files.write(stage.resolve(".validated"), spec.sha256().getBytes(StandardCharsets.US_ASCII));
            moveAtomic(stage, generation, cancel);
            try (FileOutputStream output = new FileOutputStream(next.toFile())) { output.write(generation.getFileName().toString().getBytes(StandardCharsets.US_ASCII)); output.getFD().sync(); }
            check(cancel); moveAtomic(next, base.resolve("active"), cancel);
            published = true; return generation;
        } finally {
            Files.deleteIfExists(next); deleteTree(base, stage);
            if (!published) deleteTree(base, generation);
        }
    }
    private static void moveAtomic(Path source, Path target, AtomicBoolean cancel) throws IOException {
        // Antivirus/indexer file handles can transiently block a Windows host test or import.
        for (int attempt = 0; ; attempt++) {
            check(cancel);
            try { Files.move(source, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); return; }
            catch (AccessDeniedException error) {
                if (attempt == 4) throw error;
                try { Thread.sleep(20L << attempt); }
                catch (InterruptedException stopped) { Thread.currentThread().interrupt(); throw new InterruptedIOException("Операция остановлена"); }
            }
        }
    }
    public static String hex(byte[] bytes) { StringBuilder out = new StringBuilder(); for (byte b : bytes) out.append(String.format(Locale.ROOT, "%02x", b & 255)); return out.toString(); }
    public static void deleteTree(Path base, Path directory) throws IOException {
        Path root = base.toAbsolutePath().normalize(), target = directory.toAbsolutePath().normalize();
        if (!target.getParent().equals(root) || !target.getFileName().toString().matches("(?:staging|generation)-[a-f0-9]{32}")) throw new IOException("Недопустимый каталог модели");
        if (!Files.exists(target)) return;
        try (java.util.stream.Stream<Path> entries = Files.walk(target)) {
            for (Path path : (Iterable<Path>)entries.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
        }
    }
}
