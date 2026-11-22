package com.k2fsa.sherpa.onnx;

/** Minimal fake of the sherpa-onnx Java API surface used by GigaAmSherpa; same shapes, no native code. */
public class FeatureConfig {
    public int sampleRate = 16000;
    public int featureDim = 80;
    public float dither = 0.0f;
}
