package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.net.*;
import android.os.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** One explicitly installed, pinned Qwen3 GGUF. A failed candidate cannot replace the active model. */
final class LlmModels {
    static final long BYTES = 396705472;
    static final String SHA256 = "ac2d97712095a558e31573f62f466a3f9d93990898b0ec79d7c974c1780d524a";
    static final String REVISION = "50968a4468ef4233ed78cd7c3de230dd1d61a56b";
    static final String URL = "https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/resolve/" + REVISION + "/Qwen3-0.6B-Q4_K_M.gguf?download=true";
    private final Context context; private final Path base, part; private final Runnable changed;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(); private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicBoolean cancel = new AtomicBoolean(); private volatile HttpURLConnection connection;
    private volatile boolean busy, closed; private volatile Path active; private volatile String status = "Проверяю модель…"; private volatile int progress = -1;
    LlmModels(Context context, Runnable changed) { this.context = context.getApplicationContext(); this.changed = changed; base = context.getFilesDir().toPath().resolve("llm-models"); part = base.resolve("qwen3-06b.part"); worker.execute(() -> { try { Files.createDirectories(base); active = readActive(base); status = active == null ? "Не установлена" : "Qwen3 0.6B установлена"; } catch (Exception error) { status = "Не удалось открыть модель. Файлы сохранены; повторите установку."; } notifyChanged(); }); }
    static Path readActive(Path base) throws IOException { return GgufInstaller.active(base, BYTES); }
    Path active() { return active; } boolean busy() { return busy; } String status() { return status; } int progress() { return progress; }
    private void notifyChanged() { main.post(() -> { if (!closed) changed.run(); }); }
    private void check() throws IOException { if (cancel.get()) throw new InterruptedIOException("Установка остановлена"); }
    void pause() { cancel.set(true); HttpURLConnection current = connection; if (current != null) current.disconnect(); }
    private interface Work { void run() throws Exception; }
    private void start(Work action) {
        if (busy || closed) return; busy = true; cancel.set(false); progress = -1; status = "Подготовка…"; notifyChanged();
        worker.execute(() -> {
            try {
                Files.createDirectories(base); if (!LocalLlmNative.supported()) throw new IOException("GGUF доступен только на поддерживаемом 64-битном Android");
                if (base.toFile().getUsableSpace() < BYTES + 200L * 1048576) throw new IOException("Нужно не менее 600 МиБ свободного места");
                action.run();
                Path old = active;
                active = GgufInstaller.install(base, part, BYTES, SHA256, cancel, candidate -> {
                    LocalLlm.requireMemory(context);
                    long handle = LocalLlmNative.load(candidate.toString()); LocalLlmNative.close(handle);
                }, phase -> { status = phase; progress = -1; notifyChanged(); });
                if (old != null && !old.equals(active)) { try { Files.deleteIfExists(old); } catch (IOException ignored) { /* Active model remains usable; old file is retained. */ } }
                status = "Qwen3 0.6B установлена и проверена движком. Можно открыть чат телефона.";
            } catch (OutOfMemoryError error) { status = "Недостаточно памяти для модели; прежняя модель сохранена"; }
            catch (Exception | LinkageError error) { status = cancel.get() ? "Остановлено. Загрузку можно продолжить." : error.getMessage() == null ? "Не удалось установить GGUF. Прежняя модель сохранена." : error.getMessage(); }
            finally { busy = false; progress = -1; connection = null; notifyChanged(); }
        });
    }
    void download(boolean wifiOnly) {
        start(() -> {
            android.net.Network network = null;
            if (wifiOnly) { ConnectivityManager manager = (ConnectivityManager)context.getSystemService(Context.CONNECTIVITY_SERVICE); network = manager.getActiveNetwork(); NetworkCapabilities caps = manager.getNetworkCapabilities(network); if (caps == null || !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) throw new IOException("Подключитесь к Wi-Fi или разрешите любую сеть"); }
            final android.net.Network selected = network;
            ResumableDownload.download(Arrays.asList(new ResumableDownload.Source("Hugging Face", new URL(URL))), part, BYTES, cancel, url -> {
                String host = url.getHost().toLowerCase(Locale.ROOT);
                if (!url.getProtocol().equals("https") || url.getUserInfo() != null || !(host.equals("huggingface.co") || host.endsWith(".hf.co"))) throw new IOException("Неподдерживаемое перенаправление модели");
                return (HttpURLConnection)(selected == null ? url.openConnection() : selected.openConnection(url));
            }, new ResumableDownload.Observer() {
                private long last;
                public void progress(String source, long done, long total) { if (SystemClock.elapsedRealtime() - last < 250 && done < total) return; last = SystemClock.elapsedRealtime(); progress = (int)(done * 100 / total); status = "Загрузка: " + done / 1048576 + " / " + total / 1048576 + " МиБ"; notifyChanged(); }
                public void retry(String source, String reason) { status = reason; notifyChanged(); }
                public void connection(HttpURLConnection current) { connection = current; }
            });
        });
    }
    void importFile(android.net.Uri uri) { start(() -> { Path imported = base.resolve("import.part"); try { try (InputStream input = context.getContentResolver().openInputStream(uri); OutputStream output = Files.newOutputStream(imported)) { if (input == null) throw new IOException("Файл недоступен"); long count = 0; byte[] buffer = new byte[65536]; int n; while ((n = input.read(buffer)) != -1) { check(); count += n; if (count > BYTES) throw new IOException("Поддерживается точный Qwen3-0.6B-Q4_K_M.gguf из каталога"); output.write(buffer, 0, n); } } Files.move(imported, part, StandardCopyOption.REPLACE_EXISTING); } finally { Files.deleteIfExists(imported); } }); }
    void discard() { if (busy) return; busy = true; worker.execute(() -> { try { Files.deleteIfExists(part); status = "Незавершённая загрузка удалена"; } catch (IOException error) { status = "Не удалось удалить незавершённую загрузку"; } finally { busy = false; notifyChanged(); } }); }
    void remove() { if (busy) return; busy = true; worker.execute(() -> { try { Files.deleteIfExists(base.resolve("active")); Path old = active; active = null; if (old != null) Files.deleteIfExists(old); status = "Модель удалена. Чаты сохранены."; } catch (IOException error) { status = "Не удалось удалить модель"; } finally { busy = false; notifyChanged(); } }); }
    void close() { closed = true; pause(); worker.shutdown(); }
}
