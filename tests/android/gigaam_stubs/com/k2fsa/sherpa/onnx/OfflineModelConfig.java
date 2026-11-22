package com.k2fsa.sherpa.onnx;

/** Stub shaped like the Kotlin data class: only the synthetic default-args constructor exists. */
public class OfflineModelConfig {
    public OfflineTransducerModelConfig transducer;
    public int numThreads = 1;
    public boolean debug = false;
    public String modelType = "";
    public String tokens = "";
    public OfflineModelConfig(int mask, kotlin.jvm.internal.DefaultConstructorMarker marker) {
        // mask 0 means every parameter keeps its Kotlin default.
        this.transducer = new OfflineTransducerModelConfig(0, marker);
        this.numThreads = 1; this.debug = false; this.modelType = ""; this.tokens = "";
    }
}
