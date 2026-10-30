package ru.wildlik.wileyai.mobile;

import java.io.IOException;

/** JNI is private to one serial generation worker; model output never executes actions. */
final class LocalLlmNative {
    private static boolean loaded;
    static { try { System.loadLibrary("wiley_llm"); loaded = true; } catch (LinkageError unsupported) { loaded = false; } }
    static boolean supported() { return loaded; }
    static native long load(String path) throws IOException;
    static native void begin(long handle, byte[] prompt) throws IOException;
    static native void grammar(long handle, byte[] grammar) throws IOException;
    static native byte[] next(long handle) throws IOException;
    static native void cancel(long handle);
    static native void close(long handle);
    private LocalLlmNative() {}
}
