package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;
import java.io.*;
import java.net.URL;
import java.nio.file.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;

/** Downloads only after an explicit UI action; old active models survive every failure. */
final class SpeechModelManager {
    interface Listener { void changed(); }
    private final Context context;
    private final Path base, partial;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private volatile java.net.HttpURLConnection connection;
    private volatile boolean busy, closed, recoveryNeeded;
    private volatile Path active;
    private volatile String detail = "Проверяю локальный комплект…";
    private volatile int percent = -1;
    private long lastProgress, began;
    private volatile long partialBytes;
    private volatile String sourceName = "", phase = "", lastDiagnostic = "";
    private final android.content.SharedPreferences diagnostics;
    private final Listener listener;
    SpeechModelManager(Context context, Listener listener) {
        this.context = context.getApplicationContext(); this.listener = listener;
        diagnostics = this.context.getSharedPreferences("wiley-speech-diagnostics", Context.MODE_PRIVATE);
        lastDiagnostic = diagnostics.getString("last", "");
        base = this.context.getFilesDir().toPath().resolve("speech-models"); partial = base.resolve("russian.zip.part");
        worker.execute(this::refresh);
    }
    Path active() { return active; }
    boolean busy() { return busy; }
    boolean removable() { return active != null || recoveryNeeded; }
    String detail() { return detail; }
    int percent() { return percent; }
    long partialBytes() { return partialBytes; }
    String diagnostic() { return lastDiagnostic.isEmpty() ? "Попыток загрузки ещё не было" : lastDiagnostic; }
    private void saveDiagnostic(String result, Throwable error) {
        try {
            partialBytes = Files.exists(partial) ? Files.size(partial) : 0;
            JSONObject record = new JSONObject().put("time", System.currentTimeMillis()).put("operation", "speech-model")
                .put("stage", phase).put("source", sourceName).put("result", result).put("partial_bytes", partialBytes)
                .put("verified_archive_bytes", result.equals("complete") ? RussianSpeechModel.SPEC.bytes() : 0)
                .put("elapsed_ms", android.os.SystemClock.elapsedRealtime() - began).put("error_class", error == null ? "" : error.getClass().getSimpleName()).put("message", detail);
            lastDiagnostic = record.toString(2); diagnostics.edit().putString("last", lastDiagnostic).apply();
        } catch (Exception ignored) { /* Diagnostics must not invalidate an installed model. */ }
    }
    private void changed() { main.post(() -> { if (!closed) listener.changed(); }); }
    private void refresh() {
        try { Files.createDirectories(base); active = VerifiedModelInstaller.active(base); cleanAbandoned(); partialBytes = Files.exists(partial) ? Files.size(partial) : 0; detail = active == null ? "Не установлен" : "Загрузка модели проверена; распознавание речи проверяется при использовании"; }
        catch (Exception e) { recoveryNeeded = true; detail = "Не удалось открыть комплект. Данные не удалены. Для восстановления удалите речевой комплект и установите его заново; история чатов сохранится."; }
        changed();
    }
    private void progress(String phase, long done, long total) {
        this.phase = phase;
        long now = android.os.SystemClock.elapsedRealtime();
        if (now - lastProgress < 200 && done != total) return;
        lastProgress = now; percent = total > 0 ? (int)(done * 100 / total) : -1;
        detail = phase + (done > 0 ? " · " + done / 1048576 + (total > 0 ? " / " + total / 1048576 : "") + " МиБ" : ""); changed();
    }
    static void validate(Path directory) throws Exception {
        for (String file : new String[]{"am/final.mdl", "conf/model.conf", "graph/HCLr.fst", "graph/Gr.fst"})
            if (!Files.isRegularFile(directory.resolve(file)) || Files.size(directory.resolve(file)) == 0) throw new IOException("В архиве нет обязательных файлов русской модели");
        org.vosk.LibVosk.setLogLevel(org.vosk.LogLevel.WARNINGS);
        try (Model model = new Model(directory.toString()); Recognizer recognizer = new Recognizer(model, 16000)) {
            recognizer.acceptWaveForm(new short[1600], 1600); new JSONObject(recognizer.getFinalResult());
        }
    }
    private interface Work { void run() throws Exception; }
    private void start(Work work) {
        if (busy || closed) return;
        busy = true; percent = -1; cancelled.set(false); began = android.os.SystemClock.elapsedRealtime(); phase = "Подготовка"; sourceName = ""; detail = "Подготовка…"; changed();
        worker.execute(() -> {
            try {
                if (closed || cancelled.get()) throw new InterruptedIOException();
                Files.createDirectories(base);
                active = VerifiedModelInstaller.active(base); cleanAbandoned();
                if (base.toFile().getUsableSpace() < RussianSpeechModel.SPACE_BUDGET) throw new IOException("Для безопасной установки нужно не менее 400 МиБ свободного места");
                work.run(); saveDiagnostic("complete", null);
            } catch (OutOfMemoryError error) { detail = "Не хватает оперативной памяти для речевой модели. Прежний комплект сохранён."; saveDiagnostic("error", error); }
            catch (LinkageError error) { detail = "Нативный движок не запустился на этом устройстве. Прежний комплект сохранён."; saveDiagnostic("error", error); }
            catch (Exception error) { detail = cancelled.get() ? "Остановлено. Загрузку можно продолжить; прежний комплект сохранён." : describe(error); saveDiagnostic(cancelled.get() ? "stopped" : "error", error); }
            finally { connection = null; busy = false; percent = -1; changed(); }
        });
    }
    private static String describe(Exception error) {
        if (error instanceof java.net.UnknownHostException) return "Сервер модели не найден. Проверьте подключение к сети или импортируйте ZIP.";
        if (error instanceof java.net.SocketTimeoutException) return "Сервер модели не ответил вовремя. Сохранённую загрузку можно продолжить.";
        if (error instanceof javax.net.ssl.SSLException) return "Не удалось проверить защищённое соединение с сервером модели. Проверка TLS не отключена.";
        String message = error.getMessage();
        return error instanceof IOException && message != null && message.matches("(?s).*[А-Яа-яЁё].*") ? message : "Не удалось прочитать, сохранить или проверить речевой комплект. Прежняя активная модель сохранена.";
    }
    private void publish() throws Exception {
        try { active = VerifiedModelInstaller.install(base, partial, RussianSpeechModel.SPEC, cancelled, this::progress, SpeechModelManager::validate); }
        catch (VerifiedModelInstaller.ChecksumException error) { Files.deleteIfExists(partial); throw error; }
        Files.deleteIfExists(partial);
        recoveryNeeded = false;
        detail = "Комплект установлен; пробная загрузка и декодирование тишины прошли. Проверьте речь микрофоном.";
        cleanAbandoned();
    }
    void download(boolean wifiOnly) {
        start(() -> {
            android.net.Network boundNetwork = null;
            if (wifiOnly) {
                ConnectivityManager network = (ConnectivityManager)context.getSystemService(Context.CONNECTIVITY_SERVICE);
                boundNetwork = network.getActiveNetwork(); NetworkCapabilities capabilities = network.getNetworkCapabilities(boundNetwork);
                if (capabilities == null || !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) throw new IOException("Для загрузки подключитесь к Wi-Fi или отключите режим «Только Wi-Fi».");
            }
            final android.net.Network selectedNetwork = boundNetwork;
            java.util.List<ResumableDownload.Source> sources = java.util.Arrays.asList(
                new ResumableDownload.Source("Vosk", new URL(RussianSpeechModel.URL)),
                new ResumableDownload.Source("Резервный сервер", new URL(RussianSpeechModel.MIRROR)));
            ResumableDownload.download(sources, partial, RussianSpeechModel.SPEC.bytes(), cancelled, url -> {
                String host = url.getHost().toLowerCase(java.util.Locale.ROOT);
                if (!url.getProtocol().equals("https") || url.getUserInfo() != null || !(host.equals("alphacephei.com") || host.equals("huggingface.co") || host.endsWith(".huggingface.co") || host.endsWith(".hf.co")))
                    throw new IOException("Источник перенаправил загрузку на неподдерживаемый адрес");
                return (HttpsURLConnection)(selectedNetwork == null ? url.openConnection() : selectedNetwork.openConnection(url));
            }, new ResumableDownload.Observer() {
                public void progress(String source, long done, long total) { sourceName = source; partialBytes = done; SpeechModelManager.this.progress("Загрузка", done, total); }
                public void retry(String source, String reason) { sourceName = source; detail = reason; changed(); }
                public void connection(java.net.HttpURLConnection active) { connection = active; }
            });
            publish();
        });
    }
    void importZip(android.net.Uri uri) {
        start(() -> {
            Path imported = base.resolve("import.zip.part");
            try {
                try (InputStream input = context.getContentResolver().openInputStream(uri); OutputStream output = Files.newOutputStream(imported)) {
                    if (input == null) throw new IOException("Не удалось открыть выбранный файл");
                    byte[] buffer = new byte[65536]; long size = 0; int n;
                    while ((n = input.read(buffer)) != -1) { if (cancelled.get()) throw new InterruptedIOException(); size += n; if (size > RussianSpeechModel.SPEC.bytes()) throw new IOException("Выбран другой ZIP: размер превышает размер русского комплекта"); output.write(buffer, 0, n); progress("Импорт", size, RussianSpeechModel.SPEC.bytes()); }
                }
                active = VerifiedModelInstaller.install(base, imported, RussianSpeechModel.SPEC, cancelled, this::progress, SpeechModelManager::validate);
                recoveryNeeded = false;
                detail = "Импорт и пробная загрузка прошли. Проверьте русскую речь микрофоном."; cleanAbandoned();
            } finally { Files.deleteIfExists(imported); }
        });
    }
    void pause() { cancelled.set(true); java.net.HttpURLConnection http = connection; if (http != null) http.disconnect(); }
    void discardPartial() {
        if (busy) return;
        busy = true; changed();
        worker.execute(() -> { try { Files.deleteIfExists(partial); partialBytes = 0; detail = "Незавершённая загрузка удалена"; } catch (IOException e) { detail = "Не удалось удалить незавершённую загрузку"; } finally { busy = false; changed(); } });
    }
    void remove() {
        if (busy) return;
        busy = true; changed();
        worker.execute(() -> {
            try { Files.deleteIfExists(base.resolve("active")); active = null; cleanAbandoned(); recoveryNeeded = false; detail = "Речевой комплект удалён"; }
            catch (Exception e) { recoveryNeeded = true; detail = "Не удалось полностью удалить комплект; повторите удаление"; }
            finally { busy = false; changed(); }
        });
    }
    private void cleanAbandoned() throws IOException {
        Files.deleteIfExists(base.resolve("import.zip.part"));
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(base)) {
            for (Path entry : entries) {
                String name = entry.getFileName().toString();
                if (name.matches("(?:staging|generation)-[a-f0-9]{32}") && !entry.equals(active)) VerifiedModelInstaller.deleteTree(base, entry);
                else if (name.matches("pointer-[a-f0-9]{32}")) Files.deleteIfExists(entry);
            }
        }
    }
    void close() { closed = true; pause(); worker.shutdown(); }
}
