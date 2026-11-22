package ru.wildlik.wileyai.mobile;

import android.content.Context;
import java.io.IOException;
import java.nio.file.Path;
import java.util.Arrays;
import org.json.*;
import org.vosk.Recognizer;

import static ru.wildlik.wileyai.mobile.AcousticStore.*;

/** Saved PCM only. Decoder instances have no callback to the production wake flow. */
final class AcousticReplay {
    static JSONObject vosk(Context app, short[] pcm, JSONObject event, java.util.function.BooleanSupplier cancelled) throws Exception {
        Path installed = VerifiedModelInstaller.active(app.getFilesDir().toPath().resolve("speech-models"));
        if (installed == null) throw new IOException("missing_vosk");
        String preset = event.optString("preset", app.getSharedPreferences("wiley-mobile", 0)
                .getString("wake_phrase", WakeSettings.defaultPhrase(app)));
        if (!WakePhrase.valid(preset)) preset = WakePhrase.DEFAULT;
        JSONArray observations = new JSONArray();
        try (SpeechRuntime.Lease lease = SpeechRuntime.acquire(installed)) {
            String grammar = event.optString("grammar", "");
            if (grammar.isEmpty()) grammar = WakeVocabulary.grammar(lease.model(), preset);
            try (Recognizer decoder = new Recognizer(lease.model(), AcousticCapture.RATE, grammar)) {
                decoder.setWords(true);
                int accepted = 0;
                for (int start = 0; start < pcm.length; start += 2048) {
                    if (cancelled.getAsBoolean()) throw new java.util.concurrent.CancellationException();
                    short[] block = Arrays.copyOfRange(pcm, start, Math.min(pcm.length, start + 2048));
                    if (!decoder.acceptWaveForm(block, block.length)) continue;
                    JSONObject output = new JSONObject(decoder.getResult());
                    JSONArray words = output.optJSONArray("result");
                    double confidence = words == null || words.length() == 0 ? Double.NaN : 1;
                    if (words != null) for (int i = 0; i < words.length(); i++) confidence = Math.min(confidence, words.getJSONObject(i).optDouble("conf", 0));
                    String heard = output.optString("text");
                    boolean hit = WakePhrase.conversation(preset, heard, confidence) || WakePhrase.matches(preset, heard, confidence);
                    if (hit) accepted++;
                    observations.put(fields("file_sample", start + block.length, "accepted", hit,
                            "confidence", Double.isFinite(confidence) ? confidence : null, "final", output));
                }
                return fields("status", "ok", "preset", preset, "grammar", grammar, "threshold", WakePhrase.MIN_CONFIDENCE,
                        "decoder", "reset_at_excerpt_start; 2048; no synthetic tail; all finals", "accepted", accepted,
                        "observations", observations);
            }
        }
    }
    private AcousticReplay() {}
}
