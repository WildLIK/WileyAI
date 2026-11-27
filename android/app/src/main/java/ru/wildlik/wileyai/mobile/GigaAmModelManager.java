package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** GigaAM v3 model files: explicit download or ZIP import; old active model survives every failure. */
final class GigaAmModelManager {
    interface Listener { void changed(); }
    private final Context context;
    private final Path base, downloadDirectory;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private final android.content.SharedPreferences diagnostics;
    private final Listener listener;
    private volatile java.net.HttpURLConnection connection;
    private volatile boolean busy, closed, recoveryNeeded;
    private volatile Path active;
    private volatile String detail = "Проверяю модель GigaAM…", phase = "", sourceName = "", lastDiagnostic = "";
    private volatile int percent = -1;
    private volatile long partialBytes;
    private long lastProgress, began;
    GigaAmModelManager(Context context, Listener listener) {
        this.context = context.getApplicationContext(); this.listener = listener;
        diagnostics = this.context.getSharedPreferences("wiley-gigaam-diagnostics", Context.MODE_PRIVATE);
        lastDiagnostic = diagnostics.getString("last", "");
        base = this.context.getFilesDir().toPath().resolve("asr-models");
        downloadDirectory = base.resolve("staging-" + GigaAmModel.ENCODER.sha256().substring(0, 32));
        worker.execute(this::refresh);
    }
    Path active() { return active; }
    boolean busy() { return busy; }
    boolean removable() { return active != null || recoveryNeeded; }
    String detail() { return detail; }
    int percent() { return percent; }
    long partialBytes() { return partialBytes; }
    String diagnostic() { return lastDiagnostic.isEmpty() ? "Попыток загрузки ещё не было" : lastDiagnostic; }
    /** The engine resolves the active directory itself; the manager stays optional at runtime. */
    static Path activeModel(Context context) {
        try { return VerifiedModelInstaller.active(context.getFilesDir().toPath().resolve("asr-models")); }
        catch (IOException damaged) { return null; }
    }
    private long savedBytes() throws IOException {
        long saved = 0;
        for (GigaAmModel.File spec : GigaAmModel.FILES) {
            Path file = downloadDirectory.resolve(spec.name());
            if (Files.isRegularFile(file)) saved += Math.min(Files.size(file), spec.bytes());
        }
        return saved;
    }
    private void saveDiagnostic(String result, Throwable error) {
        try {
            partialBytes = savedBytes();
            org.json.JSONObject record = new org.json.JSONObject().put("time", System.currentTimeMillis()).put("operation", "gigaam-model")
                .put("stage", phase).put("source", sourceName).put("result", result).put("partial_bytes", partialBytes)
                .put("verified_total_bytes", result.equals("complete") ? GigaAmModel.totalBytes() : 0)
                .put("elapsed_ms", android.os.SystemClock.elapsedRealtime() - began).put("error_class", error == null ? "" : error.getClass().getSimpleName()).put("message", detail);
            lastDiagnostic = record.toString(2); diagnostics.edit().putString("last", lastDiagnostic).apply();
        } catch (Exception ignored) { /* Diagnostics must not invalidate an installed model. */ }
    }
    private void changed() { main.post(() -> { if (!closed) listener.changed(); }); }
    private void refresh() {
        try {
            Files.createDirectories(base);
            active = VerifiedModelInstaller.active(base);
            cleanAbandoned();
            partialBytes = savedBytes();
            detail = active != null ? "Модель установлена; декодирование проверяется при использовании"
                    : partialBytes > 0 ? "Часть модели сохранена. Загрузку можно продолжить." : "Не установлена";
        } catch (Exception damaged) {
            recoveryNeeded = true; active = null;
            detail = "Не удалось открыть модель. Данные не удалены. Для восстановления удалите модель и установите заново.";
        }
        changed();
    }
    private void progress(String phase, long done, long total) {
        this.phase = phase;
        long now = android.os.SystemClock.elapsedRealtime();
        if (now - lastProgress < 200 && done != total) return;
        lastProgress = now; percent = total > 0 ? (int)(done * 100 / total) : -1;
        detail = phase + (done > 0 ? " · " + done / 1048576 + (total > 0 ? " / " + total / 1048576 : "") + " МиБ" : ""); changed();
    }
    /** Structural validation: every pinned file present with exact bytes and a parsable token list. */
    static void validate(Path directory) throws Exception {
        for (GigaAmModel.File spec : GigaAmModel.FILES) {
            Path file = directory.resolve(spec.name());
            if (!Files.isRegularFile(file) || Files.size(file) != spec.bytes()) throw new IOException("Файл модели отсутствует или имеет другой размер: " + spec.name());
        }
        int tokens = 0;
        try (BufferedReader reader = Files.newBufferedReader(directory.resolve("tokens.txt"), StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                String[] fields = line.trim().split("\\s+");
                if (fields.length < 1 || fields.length > 2) throw new IOException("Некорректный список токенов модели");
                if (fields.length == 2) Integer.parseInt(fields[1]);
                tokens++;
            }
        }
        if (tokens < 30) throw new IOException("Список токенов модели неполон");
    }
    private void publish(Path staging, AtomicBoolean cancel) throws Exception {
        progress("Проверка модели", 0, 0); validate(staging);
        String suffix = UUID.randomUUID().toString().replace("-", "");
        Path generation = base.resolve("generation-" + suffix), pointer = base.resolve("pointer-" + suffix);
        boolean published = false;
        try {
            Files.write(staging.resolve(".validated"), GigaAmModel.ENCODER.sha256().getBytes(StandardCharsets.US_ASCII));
            moveAtomic(staging, generation, cancel);
            try (FileOutputStream output = new FileOutputStream(pointer.toFile())) { output.write(generation.getFileName().toString().getBytes(StandardCharsets.US_ASCII)); output.getFD().sync(); }
            moveAtomic(pointer, base.resolve("active"), cancel);
            published = true; active = generation; recoveryNeeded = false;
            detail = "Модель установлена и проверена по файлам. Декодирование проверяется при первом использовании."; cleanAbandoned();
        } finally {
            Files.deleteIfExists(pointer);
            if (!published && Files.exists(generation)) Files.move(generation, staging, StandardCopyOption.ATOMIC_MOVE);
        }
    }
    private static void moveAtomic(Path source, Path target, AtomicBoolean cancel) throws IOException {
        for (int attempt = 0; ; attempt++) {
            if (cancel.get()) throw new InterruptedIOException("Операция остановлена");
            try { Files.move(source, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); return; }
            catch (AccessDeniedException blocked) {
                if (attempt == 4) throw blocked;
                try { Thread.sleep(20L << attempt); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); throw new InterruptedIOException("Операция остановлена"); }
            }
        }
    }
    private interface Work { void run() throws Exception; }
    private void start(boolean resume, Work work) {
        if (busy || closed) return;
        busy = true; percent = -1; cancelled.set(false); began = android.os.SystemClock.elapsedRealtime(); phase = "Подготовка"; detail = "Подготовка…"; changed();
        worker.execute(() -> {
            try {
                if (closed || cancelled.get()) throw new InterruptedIOException();
                Files.createDirectories(base);
                active = VerifiedModelInstaller.active(base); cleanAbandoned();
                long required = GigaAmModel.SPACE_BUDGET - (resume ? savedBytes() : 0);
                if (base.toFile().getUsableSpace() < required) throw new IOException("Недостаточно свободного места для оставшихся файлов GigaAM");
                work.run(); saveDiagnostic("complete", null);
            } catch (OutOfMemoryError error) { detail = "Не хватает оперативной памяти для установки модели. Прежняя модель сохранена."; saveDiagnostic("error", error); }
            catch (Exception error) {
                detail = cancelled.get() ? "Остановлено. Загрузку можно продолжить; прежняя модель сохранена." : describe(error);
                saveDiagnostic(cancelled.get() ? "stopped" : "error", error);
            } finally { connection = null; busy = false; percent = -1; changed(); }
        });
    }
    private static String describe(Exception error) {
        if (error instanceof java.net.UnknownHostException) return "Сервер модели не найден. Проверьте подключение к сети.";
        if (error instanceof java.net.SocketTimeoutException) return "Сервер модели не ответил вовремя. Незавершённую загрузку можно продолжить.";
        if (error instanceof javax.net.ssl.SSLException) return "Не удалось проверить защищённое соединение. TLS не отключается.";
        if (error instanceof ChecksumException) return error.getMessage();
        String message = error.getMessage();
        return error instanceof IOException && message != null && message.matches("(?s).*[А-Яа-яЁё].*") ? message : "Не удалось скачать или сохранить модель GigaAM. Прежняя модель сохранена.";
    }
    private static final class ChecksumException extends IOException {
        ChecksumException(String message) { super(message); }
    }
    void download(boolean wifiOnly) {
        start(true, () -> {
            Files.createDirectories(downloadDirectory);
            long downloaded = 0;
            for (GigaAmModel.File spec : GigaAmModel.FILES) {
                long prior = downloaded;
                var sources = List.of(ModelDownload.mirror("gigaam-v3-" + spec.name()),
                    ModelDownload.source("Hugging Face", GigaAmModel.BASE + spec.name()));
                ResumableDownload.download(sources, downloadDirectory.resolve(spec.name()), spec.bytes(), spec.sha256(),
                    cancelled, url -> ModelDownload.connect(context, wifiOnly, url), new ResumableDownload.Observer() {
                    public void progress(String source, long done, long total) {
                        sourceName = source;
                        partialBytes = prior + done;
                        GigaAmModelManager.this.progress("Загрузка " + spec.name() + " · " + source, prior + done, GigaAmModel.totalBytes());
                    }
                    public void retry(String source, String reason) { sourceName = source; detail = reason; changed(); }
                    public void connection(java.net.HttpURLConnection active) { connection = active; }
                });
                downloaded += spec.bytes();
            }
            publish(downloadDirectory, cancelled);
        });
    }
    void importZip(android.net.Uri uri) {
        start(false, () -> {
            Path imported = base.resolve("gigaam-import.zip");
            try {
                try (InputStream input = context.getContentResolver().openInputStream(uri); OutputStream output = Files.newOutputStream(imported)) {
                    if (input == null) throw new IOException("Не удалось открыть выбранный файл");
                    byte[] block = new byte[65536]; long size = 0; int n;
                    while ((n = input.read(block)) != -1) {
                        if (cancelled.get()) throw new InterruptedIOException();
                        size += n; if (size > GigaAmModel.totalBytes() * 2) throw new IOException("Выбранный файл слишком большой для модели GigaAM");
                        output.write(block, 0, n); progress("Импорт", size, GigaAmModel.totalBytes());
                    }
                }
                Path staging = base.resolve("staging-" + UUID.randomUUID().toString().replace("-", ""));
                try {
                    Files.createDirectories(staging);
                    Set<String> seen = new HashSet<>();
                    try (ZipInputStream zip = new ZipInputStream(Files.newInputStream(imported))) {
                        ZipEntry entry;
                        while ((entry = zip.getNextEntry()) != null) {
                            if (cancelled.get()) throw new InterruptedIOException();
                            String name = entry.getName();
                            if (entry.isDirectory() || name.contains("..") || name.startsWith("/")) continue;
                            String simple = Paths.get(name.replace('\\', '/')).getFileName().toString();
                            GigaAmModel.File spec = GigaAmModel.byName(simple);
                            if (spec == null || !seen.add(simple)) continue;
                            Path target = staging.resolve(simple);
                            try (OutputStream output = Files.newOutputStream(target, StandardOpenOption.CREATE_NEW)) {
                                MessageDigest sha = MessageDigest.getInstance("SHA-256"); long written = 0; int n;
                                byte[] block = new byte[65536];
                                while ((n = zip.read(block)) != -1) {
                                    if (cancelled.get()) throw new InterruptedIOException();
                                    written += n; if (written > spec.bytes()) throw new ChecksumException("Файл " + simple + " больше ожидаемого");
                                    sha.update(block, 0, n); output.write(block, 0, n);
                                }
                                if (written != spec.bytes() || !VerifiedModelInstaller.hex(sha.digest()).equals(spec.sha256())) throw new ChecksumException("Контрольная сумма " + simple + " не совпала");
                            }
                        }
                    }
                    if (seen.size() != GigaAmModel.FILES.size()) throw new ChecksumException("В ZIP нет всех файлов модели GigaAM");
                    publish(staging, cancelled);
                } finally { VerifiedModelInstaller.deleteTree(base, staging); }
            } finally { Files.deleteIfExists(imported); }
        });
    }
    void pause() { cancelled.set(true); java.net.HttpURLConnection http = connection; if (http != null) http.disconnect(); }
    void discardPartial() {
        if (busy) return;
        busy = true; changed();
        worker.execute(() -> { try { VerifiedModelInstaller.deleteTree(base, downloadDirectory); Files.deleteIfExists(base.resolve("gigaam-download.part")); partialBytes = 0; detail = "Незавершённая загрузка удалена"; } catch (IOException failed) { detail = "Не удалось удалить незавершённую загрузку"; } finally { busy = false; changed(); } });
    }
    void remove() {
        if (busy) return;
        busy = true; changed();
        worker.execute(() -> {
            try { Files.deleteIfExists(base.resolve("active")); active = null; cleanAbandoned(); recoveryNeeded = false; detail = "Модель GigaAM удалена"; }
            catch (Exception failed) { recoveryNeeded = true; detail = "Не удалось полностью удалить модель; повторите удаление"; }
            finally { busy = false; changed(); }
        });
    }
    private void cleanAbandoned() throws IOException {
        Files.deleteIfExists(base.resolve("gigaam-import.zip"));
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(base)) {
            for (Path entry : entries) {
                String name = entry.getFileName().toString();
                if (name.matches("(?:staging|generation)-[a-f0-9]{32}") && !entry.equals(active) && !entry.equals(downloadDirectory))
                    VerifiedModelInstaller.deleteTree(base, entry);
                else if (name.matches("pointer-[a-f0-9]{32}")) Files.deleteIfExists(entry);
            }
        }
    }
    void close() { closed = true; pause(); worker.shutdown(); }
}
