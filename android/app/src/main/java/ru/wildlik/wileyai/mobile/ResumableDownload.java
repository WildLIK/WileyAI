package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.*;

/** Resumes a pinned file across mirrors and verifies the complete payload before returning. */
public final class ResumableDownload {
    public record Source(String name, URL url) {}
    public interface Connections { HttpURLConnection open(URL url) throws IOException; }
    public interface Observer {
        void progress(String source, long done, long total);
        void retry(String source, String reason);
        default void connection(HttpURLConnection connection) {}
    }
    private static final int ROUNDS = 3;
    private static final Pattern CONTENT_RANGE = Pattern.compile("bytes ([0-9]+)-([0-9]+)/([0-9]+)");
    private ResumableDownload() {}
    private static void check(AtomicBoolean cancelled) throws InterruptedIOException {
        if (cancelled.get() || Thread.currentThread().isInterrupted()) throw new InterruptedIOException("Загрузка остановлена");
    }
    public static void download(List<Source> sources, Path file, long expected, String sha256, AtomicBoolean cancelled, Connections factory, Observer observer) throws IOException {
        if (expected < 1 || sources.isEmpty() || !sha256.matches("[0-9a-f]{64}")) throw new IOException("Некорректный каталог модели");
        Files.createDirectories(file.toAbsolutePath().getParent());
        if (Files.exists(file) && Files.size(file) > expected) throw new IOException("Частичный файл больше ожидаемого. Сбросьте незавершённую загрузку.");
        IOException last = null;
        for (int round = 0; round < ROUNDS; round++) {
            for (int index = 0; index < sources.size(); index++) {
                Source source = sources.get(index);
                check(cancelled);
                try {
                    long offset = Files.exists(file) ? Files.size(file) : 0;
                    for (int requests = 0; offset < expected; requests++) {
                        if (requests == 256) throw new IOException("Сервер возвращает слишком маленькие части файла");
                        transfer(source, file, expected, offset, factory, observer, cancelled);
                        offset = Files.size(file);
                    }
                    if (!matchesDigest(file, sha256, cancelled)) {
                        check(cancelled);
                        Files.delete(file);
                        throw new IOException("Контрольная сумма файла не совпала. Неверная копия удалена.");
                    }
                    return;
                } catch (IOException error) {
                    check(cancelled);
                    last = error;
                    if (index + 1 < sources.size()) {
                        String next = sources.get(index + 1).name();
                        observer.retry(next, "Источник " + source.name() + " не сработал. Пробую " + next + "…");
                    }
                }
            }
            if (round + 1 < ROUNDS) {
                observer.retry(sources.get(0).name(), "Повторяю загрузку с сохранённого места…");
                try { Thread.sleep(250L * (round + 1)); }
                catch (InterruptedException stopped) { Thread.currentThread().interrupt(); throw new InterruptedIOException("Загрузка остановлена"); }
            }
        }
        if (last != null) throw last;
        throw new IOException("Загрузка модели не завершена");
    }
    private static boolean matchesDigest(Path file, String sha256, AtomicBoolean cancelled) throws IOException {
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException unavailable) { throw new IOException("SHA-256 недоступен", unavailable); }
        try (InputStream input = Files.newInputStream(file)) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = input.read(buffer)) != -1) {
                check(cancelled);
                digest.update(buffer, 0, count);
            }
        }
        check(cancelled);
        byte[] actual = digest.digest();
        for (int index = 0; index < actual.length; index++) {
            int expected = Integer.parseInt(sha256.substring(2 * index, 2 * index + 2), 16);
            if (Byte.toUnsignedInt(actual[index]) != expected) return false;
        }
        return true;
    }
    private static void transfer(Source source, Path file, long total, long offset, Connections factory, Observer observer, AtomicBoolean cancelled) throws IOException {
        URL target = source.url();
        for (int hop = 0; hop < 6; hop++) {
            check(cancelled); HttpURLConnection http = factory.open(target); observer.connection(http);
            try {
                check(cancelled);
                http.setInstanceFollowRedirects(false); http.setConnectTimeout(10000); http.setReadTimeout(20000);
                http.setRequestProperty("Accept-Encoding", "identity"); http.setRequestProperty("User-Agent", "WileyAI-Android/0.5");
                http.setRequestProperty("Range", "bytes=" + offset + "-" + (total - 1));
                int code = http.getResponseCode();
                if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                    String location = http.getHeaderField("Location");
                    if (location == null || location.length() > 16000) throw new IOException("Сервер прислал некорректное перенаправление");
                    target = new URL(target, location); continue;
                }
                long start = offset, responseBytes;
                if (code == 200) { start = 0; responseBytes = total; }
                else if (code == 206) {
                    Matcher range = CONTENT_RANGE.matcher(String.valueOf(http.getHeaderField("Content-Range")));
                    if (!range.matches()) throw new IOException("Сервер прислал некорректный диапазон файла");
                    try {
                        long first = Long.parseLong(range.group(1)), end = Long.parseLong(range.group(2)), length = Long.parseLong(range.group(3));
                        if (first != offset || end < first || end >= total || length != total) throw new IOException("Диапазон файла не совпадает с ожидаемым");
                        responseBytes = end - first + 1;
                    } catch (NumberFormatException invalid) { throw new IOException("Некорректный размер диапазона файла"); }
                } else throw new IOException("Источник модели вернул HTTP " + code);
                String encoding = http.getContentEncoding();
                if (encoding != null && !encoding.equalsIgnoreCase("identity")) throw new IOException("Сервер изменил кодировку архива");
                long declaredBytes = http.getContentLengthLong();
                if (declaredBytes >= 0 && declaredBytes != responseBytes) throw new IOException("Размер ответа сервера не совпадает с ожидаемым");
                try (InputStream input = http.getInputStream(); OutputStream output = Files.newOutputStream(file, StandardOpenOption.CREATE, start == 0 ? StandardOpenOption.TRUNCATE_EXISTING : StandardOpenOption.APPEND)) {
                    byte[] buffer = new byte[65536]; long received = 0; int count;
                    while ((count = input.read(buffer)) != -1) {
                        check(cancelled);
                        if (received + count > responseBytes || start + received + count > total) throw new IOException("Источник прислал лишние данные вместо архива");
                        output.write(buffer, 0, count); received += count; observer.progress(source.name(), start + received, total);
                    }
                    if (received != responseBytes) throw new EOFException("Связь прервалась до конца части файла");
                }
                return;
            } finally { http.disconnect(); observer.connection(null); }
        }
        throw new IOException("Слишком много перенаправлений при загрузке модели");
    }
}
