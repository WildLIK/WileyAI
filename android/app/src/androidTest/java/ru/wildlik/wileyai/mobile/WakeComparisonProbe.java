package ru.wildlik.wileyai.mobile;

import android.content.Context;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;

/** A frozen archived PCM smoke test. No microphone or action routing is used. */
final class WakeComparisonProbe {
    static String run(Context context) throws Exception {
        long handle = 0;
        try {
            var sample = context.getCacheDir().toPath().resolve("wake-next16-archived-probe.pcm");
            byte[] bytes = Files.readAllBytes(sample);
            if (bytes.length != 63 * 1280 * 2) throw new AssertionError("Unexpected fixture");
            ByteBuffer pcm = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
            System.loadLibrary("wiley_livekit_compare");
            handle = WakeComparison.open(WakeComparison.verifiedModel(context).toString());
            if (handle == 0) throw new AssertionError("Could not open ONNX");
            float[] first = scores(handle, pcm);
            if (!WakeComparison.reset(handle)) throw new AssertionError("Reset failed");
            pcm.rewind();
            float[] second = scores(handle, pcm);
            if (!Arrays.equals(first, second)) throw new AssertionError("Reset parity");
            var rule = new WakeComparisonPcm.Decision();
            var events = new ArrayList<Long>();
            for (int i = 0; i < first.length; i++)
                if (rule.update((i + 1L) * 1280, first[i])) events.add((i + 1L) * 1280);
            if (!events.equals(java.util.List.of(16640L))) throw new AssertionError("Expected archived PCM event");
            return "63 blocks; same position on restart; sample=16640; microphone not opened";
        } finally {
            if (handle != 0) WakeComparison.close(handle);
        }
    }

    private static float[] scores(long handle, ByteBuffer pcm) {
        float[] values = new float[63];
        short[] chunk = new short[1280];
        for (int i = 0; i < values.length; i++) {
            for (int j = 0; j < chunk.length; j++) chunk[j] = pcm.getShort();
            values[i] = WakeComparison.score(handle, chunk);
            if (!Float.isFinite(values[i])) throw new AssertionError("Invalid score");
        }
        return values;
    }
}
