package android.speech.tts;
public abstract class UtteranceProgressListener {
 public void onAudioAvailable(String id, byte[] samples) {}
 public void onBeginSynthesis(String id,int sampleRate,int audioFormat,int channels) {}
    public abstract void onStart(String id); public abstract void onDone(String id); public abstract void onError(String id);
    public void onStop(String id,boolean interrupted){}
}
