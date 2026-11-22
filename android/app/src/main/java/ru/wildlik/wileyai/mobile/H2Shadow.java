package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.SystemClock;
import android.util.AtomicFile;
import java.io.*;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** In-memory opt-in. No audio input, recognizer callback, or command executor. */
final class H2Shadow {
    private static native long open(String directory);
    private static native float score(long handle, short[] pcm);
    private static native void close(long handle);
    private static final int MINUTES = 5;
    private static volatile H2Shadow instance;
    private static volatile String state = "Выключено";
    private final H2Windows queue = new H2Windows();
    private final File directory;
    private final AtomicFile output;
    private volatile boolean stopped, ready;
    private volatile int processed;
    private volatile long voskFinals;
    private final JSONArray events = new JSONArray();

    private H2Shadow(Context context) {
        directory = new File(context.getNoBackupFilesDir(),"h2-next10");
        output = report(context);
    }
    static AtomicFile report(Context context) {
        return new AtomicFile(new File(context.getNoBackupFilesDir(),"h2-last.json"));
    }
    static synchronized void start(Context context) {
        if (instance != null) return;
        H2Shadow s = new H2Shadow(context);
        instance = s;
        state = "Подготовка H2";
        new Thread(s::run,"H2-observer").start();
    }
    static synchronized void stop() {
        if (instance != null) instance.stopped = true;
    }
    static String status() {
        H2Shadow s = instance;
        return s == null || !s.ready ? state : "Наблюдение H2 · окон " + s.processed + " · пропущено " + s.queue.dropped;
    }
    static void feed(long capture, long first, short[] data, int count) {
        H2Shadow s = instance;
        if (s != null && s.ready && !s.stopped) s.queue.feed(capture,first,data,count);
    }
    static void end(long capture) {
        H2Shadow s = instance;
        if (s != null && s.ready) s.queue.end(capture);
    }
    static void voskAccepted() {
        H2Shadow s = instance;
        if (s != null && s.ready) s.voskFinals++;
    }
    private void verify(String name, String expected, int size) throws Exception {
        File file = new File(directory,name);
        if (file.length() != size) throw new IOException("Missing frozen research files");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] block = new byte[16384];
            for (int n; (n=input.read(block))!=-1;) digest.update(block,0,n);
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest()) hex.append(String.format(Locale.ROOT,"%02x",b));
        if (!expected.contentEquals(hex)) throw new IOException("Unexpected research file");
    }
    private void run() {
        long start = SystemClock.elapsedRealtime(), cpu = android.os.Debug.threadCpuTimeNanos(), handle=0, init=-1;
        String reason = "user_stop";
        ArrayList<Double> costs = new ArrayList<>();
        H2Windows.Decision decision = new H2Windows.Decision();
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND);
            verify("multi.onnx","6258bf82d30870e240e5927dd06987170c1dc3615dcaf0c95071ccceacdacb49",3057692);
            verify("filters.bin","a16a08140d9cfe30e39271485a5bc91349a39a237a5ab470b027e4650e6bfab6",135424);
            verify("head.bin","58a7b4b0255f1b36f642850d57a5ac0a11a77a643b9a942affffae30671fdab1",1986560);
            System.loadLibrary("wiley_h2");
            handle=open(directory.getAbsolutePath());
            if (handle==0) throw new IllegalStateException();
            init=SystemClock.elapsedRealtime()-start;
            ready=true;
            while (!stopped && SystemClock.elapsedRealtime()-start < MINUTES*60000L) {
                H2Windows.Slot slot = queue.next();
                if (slot==null) { SystemClock.sleep(10); continue; }
                long began=SystemClock.elapsedRealtimeNanos();
                float value=score(handle,slot.pcm);
                if (!Float.isFinite(value)) throw new IllegalStateException();
                costs.add((SystemClock.elapsedRealtimeNanos()-began)/1e6);
                if (decision.update(slot.capture,slot.end,value)) {
                    events.put(new JSONObject().put("capture",slot.capture).put("end_sample",slot.end).put("score",value));
                }
                processed++;
                queue.release(slot);
            }
            if (!stopped) reason="timeout";
        } catch (IOException absent) { reason="assets"; }
        catch (Exception | LinkageError | OutOfMemoryError error) { reason="engine"; }
        finally {
            ready=false;
            long pending=queue.close();
            if (handle!=0) close(handle);
            long elapsed=SystemClock.elapsedRealtime()-start;
            long threadCpu=(android.os.Debug.threadCpuTimeNanos()-cpu)/1000000;
            String resultState = "Завершено · окон " + processed + " · срабатываний " + events.length();
            if (reason.equals("assets")) resultState = "Проверьте исследовательские файлы H2";
            if (reason.equals("engine")) resultState = "Ошибка запуска или вычисления H2";
            FileOutputStream stream=null;
            try {
                double[] times=new double[costs.size()];
                for(int i=0;i<times.length;i++) times[i]=costs.get(i);
                Arrays.sort(times);
                JSONObject result = new JSONObject().put("schema",1).put("method","NEXT7_H2").put("reason",reason)
                    .put("elapsed_ms",elapsed).put("init_ms",init).put("thread_cpu_ms",threadCpu)
                    .put("windows",processed).put("overload_drops",queue.dropped).put("warmup_windows",queue.warmup)
                    .put("pending_on_exit",pending).put("vosk_accepted",voskFinals).put("events",events);
                if (times.length>0) result.put("window_p50_ms",percentile(times,.5)).put("window_p95_ms",percentile(times,.95));
                stream=output.startWrite();
                stream.write(result.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
                output.finishWrite(stream);
            } catch (Exception failure) { if(stream!=null) output.failWrite(stream); resultState+=" · ошибка сохранения"; }
            synchronized (H2Shadow.class) { state=resultState; instance=null; }
        }
    }
    private static double percentile(double[] a,double p) {
        double x=(a.length-1)*p;
        int i=(int)x;
        return a[i]+(x-i)*(a[(int)Math.ceil(x)]-a[i]);
    }
}
