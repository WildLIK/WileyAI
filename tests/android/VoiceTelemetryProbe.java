package ru.wildlik.wileyai.mobile;

public final class VoiceTelemetryProbe {
    static void check(boolean ok){if(!ok)throw new AssertionError();}
    public static void main(String[] args){
        check(!VoiceTelemetry.snapshot().wakeRunning());
        VoiceTelemetry.wakeStarted();check(VoiceTelemetry.snapshot().wakeRunning());
        VoiceTelemetry.Capture wake=VoiceTelemetry.captureOpened(VoiceTelemetry.WAKE);
        check(VoiceTelemetry.snapshot().wakeCaptureActive()&&VoiceTelemetry.snapshot().captureCount()==1);
        VoiceTelemetry.Capture speech=VoiceTelemetry.captureOpened(VoiceTelemetry.GIGA);
        check(VoiceTelemetry.snapshot().captureCount()==2);
        wake.close();wake.close();check(!VoiceTelemetry.snapshot().wakeCaptureActive()&&VoiceTelemetry.snapshot().captureCount()==1);
        speech.close();VoiceTelemetry.wakeStopped();check(!VoiceTelemetry.snapshot().wakeRunning()&&VoiceTelemetry.snapshot().captureCount()==0);
        PcmHandoff p=new PcmHandoff(4,8);p.append(new short[]{1,2,3,4},4);p.activate(2);p.append(new short[]{5,6,7},3);
        short[] b=new short[4];try{check(p.read(b,1)==2);check(p.read(b,1)==3);}catch(InterruptedException e){throw new AssertionError(e);}
        PcmHandoff.Stats s=p.stats();check(s.boundarySample()==2&&s.acceptedSamples()==5&&s.deliveredSamples()==5&&s.overflowSamples()==0&&s.queuedSamples()==0);
        p.append(new short[]{8,9},2);p.close();check(p.stats().discardedSamples()==2);
        PcmHandoff q=new PcmHandoff(4,2);q.activate(0);try{q.append(new short[]{1,2,3},3);throw new AssertionError();}catch(IllegalStateException expected){}
        check(q.stats().overflowSamples()==3);q.close();
    }
}
