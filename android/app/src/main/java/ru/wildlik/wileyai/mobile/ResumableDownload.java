package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.*;

/** Chunked transfer with validated ranges, bounded retries and a verified-artifact mirror. */
public final class ResumableDownload {
    public record Source(String name, URL url) {}
    public interface Connections { HttpURLConnection open(URL url) throws IOException; }
    public interface Observer {
        void progress(String source, long done, long total);
        void retry(String source, String reason);
        default void connection(HttpURLConnection connection) {}
    }
    private static final long CHUNK = 2L * 1024 * 1024;
    private ResumableDownload() {}
    private static void check(AtomicBoolean cancelled) throws InterruptedIOException {
        if (cancelled.get() || Thread.currentThread().isInterrupted()) throw new InterruptedIOException("Загрузка остановлена");
    }
    public static void download(List<Source> sources, Path file, long expected, AtomicBoolean cancelled, Connections factory, Observer observer) throws IOException {
        if (expected < 1 || sources.isEmpty()) throw new IOException("Не задан источник модели");
        Files.createDirectories(file.toAbsolutePath().getParent());
        if (Files.exists(file) && Files.size(file) > expected) throw new IOException("Частичный файл больше ожидаемого. Сбросьте незавершённую загрузку.");
        IOException last = null;
        for (int sourceIndex = 0; sourceIndex < sources.size(); sourceIndex++) {
            Source source = sources.get(sourceIndex); int failures = 0, requests = 0;
            while (!Files.exists(file) || Files.size(file) < expected) {
                check(cancelled);
                long offset = Files.exists(file) ? Files.size(file) : 0;
                try {
                    if (++requests > 256) throw new IOException("Сервер возвращает слишком маленькие части архива");
                    transfer(source, file, expected, offset, factory, observer, cancelled); failures = 0;
                } catch (IOException error) {
                    check(cancelled); last = error;
                    if (sourceIndex + 1 < sources.size()) { observer.retry(sources.get(sourceIndex + 1).name(), "Основной источник не ответил. Продолжаю с резервного."); break; }
                    if (++failures >= 3 || requests > 256) break;
                    observer.retry(source.name(), "Связь прервалась. Повторяю с сохранённого места.");
                    try { Thread.sleep(250L * failures); }
                    catch (InterruptedException stopped) { Thread.currentThread().interrupt(); throw new InterruptedIOException("Загрузка остановлена"); }
                }
            }
            if (Files.exists(file) && Files.size(file) == expected) return;
        }
        if (last != null) throw last;
        throw new IOException("Загрузка модели не завершена");
    }
    private static void transfer(Source source, Path file, long total, long offset, Connections factory, Observer observer, AtomicBoolean cancelled) throws IOException {
        URL target = source.url(); long requestedEnd = Math.min(total - 1, offset + CHUNK - 1);
        for (int hop = 0; hop < 6; hop++) {
            check(cancelled); HttpURLConnection http = factory.open(target); observer.connection(http);
            try {
                check(cancelled);
                http.setInstanceFollowRedirects(false); http.setConnectTimeout(10000); http.setReadTimeout(20000);
                http.setRequestProperty("Accept-Encoding", "identity"); http.setRequestProperty("User-Agent", "WileyAI-Android/0.5");
                http.setRequestProperty("Range", "bytes=" + offset + "-" + requestedEnd);
                int code = http.getResponseCode();
                if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                    String location = http.getHeaderField("Location");
                    if (location == null || location.length() > 16000) throw new IOException("Сервер прислал некорректное перенаправление");
                    target = new URL(target, location); continue;
                }
                long start = offset, responseBytes;
                if (code == 200) { start = 0; responseBytes = total; }
                else if (code == 206) {
                    Matcher range = Pattern.compile("bytes ([0-9]+)-([0-9]+)/([0-9]+)").matcher(String.valueOf(http.getHeaderField("Content-Range")));
                    if (!range.matches()) throw new IOException("Сервер прислал некорректный диапазон файла");
                    try {
                        long first = Long.parseLong(range.group(1)), end = Long.parseLong(range.group(2)), length = Long.parseLong(range.group(3));
                        if (first != offset || end < first || end >= total || length != total) throw new IOException("Диапазон файла не совпадает с ожидаемым");
                        responseBytes = end - first + 1;
                    } catch (NumberFormatException invalid) { throw new IOException("Некорректный размер диапазона файла"); }
                } else throw new IOException("Источник модели вернул HTTP " + code);
                String encoding = http.getContentEncoding();
                if (encoding != null && !encoding.equalsIgnoreCase("identity")) throw new IOException("Сервер изменил кодировку архива");
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
