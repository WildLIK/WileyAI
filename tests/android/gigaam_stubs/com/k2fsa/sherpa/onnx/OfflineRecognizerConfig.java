package com.k2fsa.sherpa.onnx;

/** Stub with only the full constructor: exercises the tier-3 reflection fallback. */
public class OfflineRecognizerConfig {
    public FeatureConfig featConfig;
    public OfflineModelConfig modelConfig;
    public String decodingMethod;
    public OfflineRecognizerConfig(FeatureConfig featConfig, OfflineModelConfig modelConfig, String decodingMethod) {
        this.featConfig = featConfig; this.modelConfig = modelConfig; this.decodingMethod = decodingMethod;
    }
}
