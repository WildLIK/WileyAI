package com.k2fsa.sherpa.onnx;

public class OfflineRecognizerResult {
    private final String text;
    public OfflineRecognizerResult(String text) { this.text = text; }
    public String getText() { return text; }
}
