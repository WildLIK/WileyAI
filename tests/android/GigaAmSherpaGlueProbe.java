package ru.wildlik.wileyai.mobile;

import java.io.IOException;

/** Reflection glue against the fake sherpa-onnx API: verifies field and method names without the AAR. */
public final class GigaAmSherpaGlueProbe {
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        GigaAmSherpa backend = new GigaAmSherpa();
        long handle = backend.create("enc.onnx", "dec.onnx", "join.onnx", "tokens.txt", GigaAmModel.THREADS);
        com.k2fsa.sherpa.onnx.OfflineRecognizerConfig config = com.k2fsa.sherpa.onnx.OfflineRecognizer.lastConfig;
        check(config.featConfig.featureDim == 64 && config.featConfig.sampleRate == 16000 && config.featConfig.dither == 0.0f);
        check(config.modelConfig.modelType.equals("nemo_transducer"));
        check(config.modelConfig.numThreads == GigaAmModel.THREADS && config.modelConfig.tokens.equals("tokens.txt") && !config.modelConfig.debug);
        check(config.modelConfig.transducer.encoder.equals("enc.onnx") && config.modelConfig.transducer.decoder.equals("dec.onnx") && config.modelConfig.transducer.joiner.equals("join.onnx"));
        check(config.decodingMethod.equals("greedy_search"));
        check(com.k2fsa.sherpa.onnx.OfflineRecognizer.created == 1);
        String text = backend.decode(handle, new float[8000], 16000);
        check(text.equals("звездная карта"));
        check(com.k2fsa.sherpa.onnx.OfflineStream.released == 1);
        backend.close(handle);
        check(com.k2fsa.sherpa.onnx.OfflineRecognizer.closed == 1);
        com.k2fsa.sherpa.onnx.OfflineRecognizer.failDecode = true;
        long second = backend.create("enc.onnx", "dec.onnx", "join.onnx", "tokens.txt", GigaAmModel.THREADS);
        boolean failure = false;
        try { backend.decode(second, new float[8000], 16000); } catch (IOException expected) { failure = expected.getMessage().contains("движка"); }
        check(failure);
        check(com.k2fsa.sherpa.onnx.OfflineStream.released == 2);
        backend.close(second);
        // Missing native engine (AAR absent): the class-not-found path stays an honest message.
        com.k2fsa.sherpa.onnx.OfflineRecognizer.failDecode = false;
        check(backend.create("enc.onnx", "dec.onnx", "join.onnx", "tokens.txt", GigaAmModel.THREADS) > 0);
        System.out.println("GigaAM sherpa glue checks passed");
    }
}
