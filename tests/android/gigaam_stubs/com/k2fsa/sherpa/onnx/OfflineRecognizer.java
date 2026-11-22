package com.k2fsa.sherpa.onnx;

/** Fake recognizer: records the config shape, replays a scripted text, optional delays and failures. */
public class OfflineRecognizer {
    public static String nextText = "звездная карта";
    public static long decodeDelayMs = 0;
    public static boolean failCreate = false, failDecode = false;
    public static OfflineRecognizerConfig lastConfig;
    public static int created, closed, decoded;
    public OfflineRecognizer(android.content.res.AssetManager assets, OfflineRecognizerConfig config) {
        if (failCreate) throw new RuntimeException("onnx load failed");
        lastConfig = config; created++;
    }
    public OfflineStream createStream() { return new OfflineStream(); }
    public void decode(OfflineStream stream) {
        decoded++;
        if (decodeDelayMs > 0) { try { Thread.sleep(decodeDelayMs); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); } }
        if (failDecode) throw new RuntimeException("onnx decode failed");
    }
    public OfflineRecognizerResult getResult(OfflineStream stream) { return new OfflineRecognizerResult(nextText); }
    public void release() { closed++; }
}
