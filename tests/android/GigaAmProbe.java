package ru.wildlik.wileyai.mobile;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** GigaAM runtime lifecycle against a scripted backend; no microphone, no native code, no real weights. */
public final class GigaAmProbe {
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    static GigaAmSession.Model model(String id) { return new GigaAmSession.Model(id, id + "-encoder", id + "-decoder", id + "-joiner", id + "-tokens"); }
    static final class ScriptedBackend implements GigaAmSession.Backend {
        long createDelayMs, decodeDelayMs;
        boolean failCreate, failDecode;
        int created, closed, decoded;
        String lastText = "звездная карта";
        @Override public long create(String encoder, String decoder, String joiner, String tokens, int threads) throws IOException {
            check(GigaAmModel.THREADS == threads);
            if (createDelayMs > 0) sleep(createDelayMs);
            if (failCreate) throw new IOException("неверные файлы модели");
            created++; return 100 + created;
        }
        @Override public String decode(long handle, float[] samples, int sampleRate) throws IOException {
            check(sampleRate == 16000);
            decoded++;
            if (decodeDelayMs > 0) sleep(decodeDelayMs);
            if (failDecode) throw new IOException("ошибка onnx");
            return lastText;
        }
        @Override public void close(long handle) { closed++; }
    }
    static final class FixedMemory implements GigaAmSession.MemoryReader {
        long available = 4L * 1024 * 1024 * 1024;
        boolean low;
        @Override public GigaAmSession.Memory read() { return new GigaAmSession.Memory(available, 8L * 1024 * 1024 * 1024, low); }
    }
    static void sleep(long ms) { try { Thread.sleep(ms); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); } }
    static GigaAmSession.Output run(GigaAmSession session, GigaAmSession.Model model, float[] samples, double audioMs) throws Exception {
        try { return session.recognize(model, samples, 16000, audioMs).result.get(10, TimeUnit.SECONDS); }
        catch (java.util.concurrent.ExecutionException failed) {
            if (failed.getCause() instanceof IOException reason) throw reason; // unwrap for the scenario checks
            throw failed;
        }
    }
    static float[] samples(int ms) { return new float[16 * ms]; }
    public static void main(String[] args) throws Exception {
        // 1. Load; 2. reuse; 3. three commands with one load.
        ScriptedBackend backend = new ScriptedBackend();
        FixedMemory memory = new FixedMemory();
        List<GigaAmSession.Metrics> seen = new ArrayList<>();
        GigaAmSession session = new GigaAmSession(backend, memory, 60000, seen::add);
        GigaAmSession.Output first = run(session, model("m1"), samples(1500), 1500);
        check(first.text().equals("звездная карта") && backend.created == 1 && backend.decoded == 1);
        check(first.metrics().cold() && first.metrics().loads() == 1 && first.metrics().result().equals("completed"));
        check(first.metrics().ramBefore() > 0 && first.metrics().rtf() >= 0); // Real RTF is meaningful only on device.
        GigaAmSession.Output second = run(session, model("m1"), samples(1200), 1200);
        check(!second.metrics().cold() && backend.created == 1 && backend.decoded == 2);
        run(session, model("m1"), samples(800), 800);
        check(backend.created == 1 && backend.decoded == 3);
        // 6. Cancel during decode: the result is abandoned, native call finishes, model stays usable.
        backend.decodeDelayMs = 250;
        GigaAmSession.Ticket cancelled = session.recognize(model("m1"), samples(500), 16000, 500);
        sleep(60);
        cancelled.cancel();
        GigaAmSession.Output stopped = cancelled.result.get(10, TimeUnit.SECONDS);
        check(stopped.stopped() && backend.created == 1);
        backend.decodeDelayMs = 0;
        GigaAmSession.Output afterCancel = run(session, model("m1"), samples(500), 500);
        check(afterCancel.text().equals("звездная карта") && backend.created == 1);
        // 4. Idle timeout; 5. reload after idle.
        session.idleTimeout(80);
        int closedBefore = backend.closed;
        sleep(320);
        check(backend.closed == closedBefore + 1);
        boolean[] sawIdleUnload = {false};
        for (GigaAmSession.Metrics m : seen) if (m.result().equals("unloaded") && m.unloadReason().equals("idle")) sawIdleUnload[0] = true;
        check(sawIdleUnload[0]);
        GigaAmSession.Output reloaded = run(session, model("m1"), samples(500), 500);
        check(reloaded.metrics().cold() && backend.created == 2);
        // 9. Memory shortage before load; 15. recovery afterwards.
        memory.available = 300L * 1024 * 1024;
        boolean shortage = false;
        try { run(session, model("m1"), samples(500), 500); } catch (IOException failed) { shortage = failed.getMessage().contains("памяти"); }
        check(shortage);
        memory.available = 4L * 1024 * 1024 * 1024;
        // 8. Engine switch (identity change) unloads the previous weights.
        run(session, model("m1"), samples(500), 500);
        int createdBefore = backend.created;
        GigaAmSession.Output switched = run(session, model("m2"), samples(500), 500);
        check(switched.text().equals("звездная карта") && backend.created == createdBefore + 1);
        // 10/11. Broken model files; 12. ONNX decode error; 13. close; 14. reopen.
        backend.failCreate = true;
        boolean badFiles = false;
        try { run(session, model("bad"), samples(500), 500); } catch (IOException failed) { badFiles = failed.getMessage().contains("неверные файлы"); }
        check(badFiles);
        backend.failCreate = false;
        backend.failDecode = true;
        boolean onnxError = false;
        try { run(session, model("m2"), samples(500), 500); } catch (IOException failed) { onnxError = failed.getMessage().contains("ошибка onnx"); }
        check(onnxError);
        backend.failDecode = false;
        GigaAmSession.Output recovered = run(session, model("m2"), samples(500), 500);
        check(recovered.text().equals("звездная карта"));
        session.close();
        boolean closedSession = false;
        try { run(session, model("m2"), samples(500), 500); } catch (IOException failed) { closedSession = failed.getMessage().contains("закрыт"); }
        check(closedSession);
        // 14. Reopen: a fresh session works again.
        ScriptedBackend secondBackend = new ScriptedBackend();
        GigaAmSession reopened = new GigaAmSession(secondBackend, new FixedMemory(), 60000, m -> {});
        check(run(reopened, model("m1"), samples(500), 500).text().equals("звездная карта"));
        reopened.close();
        // 7. Cancel while queued behind a slow preparation; 16. coexists with the local model session.
        ScriptedBackend busyBackend = new ScriptedBackend(); busyBackend.createDelayMs = 500;
        GigaAmSession busy = new GigaAmSession(busyBackend, new FixedMemory(), 60000, m -> {});
        GigaAmSession.Ticket warm = busy.prepare(model("m1"));
        sleep(60);
        warm.cancel();
        GigaAmSession.Output warmResult = warm.result.get(10, TimeUnit.SECONDS);
        check(warmResult.stopped());
        GigaAmSession.Output afterWarm = run(busy, model("m1"), samples(500), 500);
        check(afterWarm.text().equals("звездная карта"));
        busy.close();
        LocalModelSession local = new LocalModelSession(new LocalModelSession.Backend() {
            public long create() { return 1; }
            public void load(long h, String path) { }
            public void prepare(long h) { }
            public void grammar(long h, byte[] g) { }
            public void begin(long h, byte[] p) { }
            public byte[] next(long h) { return null; }
            public long[] timings(long h) { return new long[]{0, 0, 0}; }
            public void finish(long h) { }
            public void cancel(long h) { }
            public void close(long h) { }
        }, () -> new LocalModelSession.Memory(4L * 1024 * 1024 * 1024, 8L * 1024 * 1024 * 1024, false), 60000, m -> {});
        ScriptedBackend parallelBackend = new ScriptedBackend(); parallelBackend.decodeDelayMs = 120;
        GigaAmSession parallelAsr = new GigaAmSession(parallelBackend, new FixedMemory(), 60000, m -> {});
        GigaAmSession.Ticket asrJob = parallelAsr.recognize(model("m1"), samples(500), 16000, 500);
        LocalModelSession.Ticket llmJob = local.generate(new LocalModelSession.Model("qwen", "qwen.gguf"), "привет", null, s -> {}, t -> {});
        check(asrJob.result.get(10, TimeUnit.SECONDS).text().equals("звездная карта"));
        check(llmJob.result.get(10, TimeUnit.SECONDS) != null);
        parallelAsr.close(); local.close();
        // 17/18/19/20: matcher-level negatives live in ScreenContextMatcherProbe; here: probe() ok and probe() failure.
        ScriptedBackend probeBackend = new ScriptedBackend();
        GigaAmSession probeSession = new GigaAmSession(probeBackend, new FixedMemory(), 60000, m -> {});
        probeSession.probe(model("m1"), new AtomicBoolean()).get(10, TimeUnit.SECONDS);
        check(probeBackend.created == 1 && probeBackend.closed == 1); // temporary candidate never stays resident
        probeBackend.failCreate = true;
        boolean probeFailed = false;
        try { probeSession.probe(model("m1"), new AtomicBoolean()).get(10, TimeUnit.SECONDS); } catch (Exception failed) { probeFailed = true; }
        check(probeFailed);
        AtomicBoolean cancelledProbe = new AtomicBoolean(true);
        probeBackend.failCreate = false;
        boolean probeCancelled = false;
        try { probeSession.probe(model("m1"), cancelledProbe).get(10, TimeUnit.SECONDS); } catch (Exception failed) { probeCancelled = true; }
        check(probeCancelled);
        probeSession.close();
        System.out.println("GigaAM lifecycle fake-backend checks passed");
    }
}
