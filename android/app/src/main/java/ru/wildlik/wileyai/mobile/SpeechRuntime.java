package ru.wildlik.wileyai.mobile;

import android.os.Handler;
import android.os.Looper;
import org.vosk.Model;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;

/** Share immutable Vosk model weights, never a decoder or microphone. Idle weights expire. */
final class SpeechRuntime {
    private static final Map<Path, Entry> models = new HashMap<>();
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final ExecutorService cleanup = Executors.newSingleThreadExecutor();
    private static final long IDLE_MILLIS = 120000;
    private static final class Entry {
        final Model model; int users; long release;
        Entry(Model model) { this.model = model; }
    }
    static final class Lease implements AutoCloseable {
        private final Path path; private final Entry entry; private boolean closed;
        private Lease(Path path, Entry entry) { this.path = path; this.entry = entry; }
        Model model() { return entry.model; }
        @Override public void close() {
            synchronized (models) {
                if (closed) return; closed = true; entry.users--; long ticket = ++entry.release;
                if (entry.users == 0) main.postDelayed(() -> cleanup.execute(() -> {
                    synchronized (models) {
                        if (entry.users == 0 && entry.release == ticket && models.get(path) == entry) {
                            models.remove(path); entry.model.close();
                        }
                    }
                }), IDLE_MILLIS);
            }
        }
    }
    static Lease acquire(Path source) throws java.io.IOException {
        Path path = source.toAbsolutePath().normalize();
        synchronized (models) {
            Entry entry = models.get(path);
            if (entry == null) {
                // A replaced model need not stay cached alongside its successor.
                Iterator<Entry> old = models.values().iterator();
                while (old.hasNext()) { Entry candidate = old.next(); if (candidate.users == 0) { old.remove(); candidate.model.close(); } }
                org.vosk.LibVosk.setLogLevel(org.vosk.LogLevel.WARNINGS);
                entry = new Entry(new Model(path.toString())); models.put(path, entry);
            }
            entry.users++; entry.release++; return new Lease(path, entry);
        }
    }
    static void trim() {
        cleanup.execute(() -> { synchronized (models) {
            Iterator<Entry> entries = models.values().iterator();
            while (entries.hasNext()) { Entry entry = entries.next(); if (entry.users == 0) { entries.remove(); entry.model.close(); } }
        }});
    }
    private SpeechRuntime() {}
}
