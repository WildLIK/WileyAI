package com.k2fsa.sherpa.onnx;

public class OfflineStream {
    public static int released;
    public float[] samples;
    public int sampleRate;
    public void acceptWaveform(float[] samples, int sampleRate) { this.samples = samples; this.sampleRate = sampleRate; }
    public void release() { released++; }
}
