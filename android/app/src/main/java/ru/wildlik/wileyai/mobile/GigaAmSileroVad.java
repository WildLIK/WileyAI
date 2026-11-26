package ru.wildlik.wileyai.mobile;

import android.content.res.AssetManager;
import java.io.IOException;
import java.lang.reflect.Method;

/** Session-local Silero v5 probabilities using the optional sherpa-onnx runtime. */
final class GigaAmSileroVad implements AutoCloseable {
    static final String ENABLED = "gigaam_silero_after_wake";
    static final String ASSET = "voice-vad/silero_vad_v5.onnx";
    static final int HOP = 512;
    private static final int CONTEXT = 64;
    private static final String SHERPA = "com.k2fsa.sherpa.onnx.";

    private final Object nativeVad;
    private final Method compute, release;
    private final float[] window = new float[CONTEXT + HOP];
    private int pending, speechFrames;
    private boolean opened, closed;

    private GigaAmSileroVad(Object nativeVad, Method compute, Method release) {
        this.nativeVad = nativeVad;
        this.compute = compute;
        this.release = release;
    }

    static GigaAmSileroVad open(AssetManager assets) throws ReflectiveOperationException, IOException {
        // The native constructor expects an existing bundled model.
        try (var model = assets.open(ASSET)) {
            if (model.read() < 0) throw new IOException("Empty Silero model");
        }
        Class<?> configType = Class.forName(SHERPA + "VadModelConfig");
        Object config = configType.getConstructor().newInstance();
        configType.getMethod("setSampleRate", int.class).invoke(config, GigaAmModel.SAMPLE_RATE);
        configType.getMethod("setNumThreads", int.class).invoke(config, 1);
        Object silero = configType.getMethod("getSileroVadModelConfig").invoke(config);
        silero.getClass().getMethod("setModel", String.class).invoke(silero, ASSET);
        silero.getClass().getMethod("setWindowSize", int.class).invoke(silero, HOP);
        Class<?> vadType = Class.forName(SHERPA + "Vad");
        Method compute = vadType.getMethod("compute", float[].class);
        Method release = vadType.getMethod("release");
        Object nativeVad = vadType.getConstructor(AssetManager.class, configType).newInstance(assets, config);
        return new GigaAmSileroVad(nativeVad, compute, release);
    }

    /** A null result means this read has not completed a 32 ms inference hop. */
    Boolean observe(short[] buffer, int length) throws ReflectiveOperationException, IOException {
        int offset = 0;
        Boolean speech = null;
        while (offset < length) {
            int n = Math.min(length - offset, HOP - pending);
            for (int i = 0; i < n; i++) window[CONTEXT + pending + i] = buffer[offset + i] / 32768f;
            pending += n;
            offset += n;
            if (pending == HOP) {
                float probability = (Float) compute.invoke(nativeVad, (Object) window);
                if (!Float.isFinite(probability)) throw new IOException("Invalid Silero probability");
                boolean above = probability >= .5f;
                speechFrames = above ? Math.min(2, speechFrames + 1) : 0;
                opened |= speechFrames == 2;
                speech = opened && above;
                System.arraycopy(window, HOP, window, 0, CONTEXT);
                pending = 0;
            }
        }
        return speech;
    }

    int pending() { return pending; }

    @Override public void close() {
        if (closed) return;
        closed = true;
        java.util.Arrays.fill(window, 0);
        try { release.invoke(nativeVad); }
        catch (ReflectiveOperationException | RuntimeException | LinkageError ignored) {
            android.util.Log.i("WileyVoice", "vad_release_error backend=silero");
        }
    }
}
