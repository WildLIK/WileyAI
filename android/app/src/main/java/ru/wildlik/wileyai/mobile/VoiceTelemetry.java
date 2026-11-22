package ru.wildlik.wileyai.mobile;

/** In-process observations only. Counts AudioRecord instances opened by WileyAI, not the OS. */
final class VoiceTelemetry {
    static final int WAKE=1,GIGA=2,VOSK=3,SAMPLE=4;
    record Snapshot(boolean wakeRunning, boolean wakeCaptureActive, int captureCount) {}
    private static boolean wakeRunning;private static int wakeCaptures,captures;
    static synchronized void wakeStarted(){wakeRunning=true;}
    static synchronized void wakeStopped(){wakeRunning=false;}
    static synchronized Capture captureOpened(int owner){captures++;if(owner==WAKE)wakeCaptures++;return new Capture(owner);}
    static synchronized Snapshot snapshot(){return new Snapshot(wakeRunning,wakeCaptures>0,captures);}
    static final class Capture implements AutoCloseable {
        private final int owner;private boolean closed;
        private Capture(int owner){this.owner=owner;}
        @Override public void close(){synchronized(VoiceTelemetry.class){if(closed)return;closed=true;captures--;if(owner==WAKE)wakeCaptures--;}}
    }
    private VoiceTelemetry(){}
}
