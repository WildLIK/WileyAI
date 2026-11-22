package android.speech.tts;
import android.content.Context;
import android.os.Looper;
import java.util.List;
import java.util.Set;
public class TextToSpeech {
    public static final int SUCCESS=0, ERROR=-1, QUEUE_FLUSH=0, QUEUE_ADD=1;
    public interface OnInitListener { void onInit(int status); }
    public static class Engine { public static final String KEY_FEATURE_NOT_INSTALLED="notInstalled"; }
    public static class EngineInfo { public String name="system",label="System"; }
    public static TextToSpeech last; public static boolean noVoices; public String engine,id; public UtteranceProgressListener listener;
    public TextToSpeech(Context c,OnInitListener init,String engine){this.engine=engine;last=this;Looper.pending.add(()->init.onInit("disabled".equals(engine)?ERROR:SUCCESS));}
    public int setOnUtteranceProgressListener(UtteranceProgressListener l){listener=l;return SUCCESS;}
    public int voiceLists, voiceSelections;
    public Set<Voice> getVoices(){voiceLists++;return noVoices?Set.of():Set.of(new Voice());}
    public String getDefaultEngine(){return "system";} public List<EngineInfo> getEngines(){return List.of(new EngineInfo());}
    public int setVoice(Voice v){voiceSelections++;return SUCCESS;} public int setSpeechRate(float v){return SUCCESS;} public int setPitch(float v){return SUCCESS;}
    public static int getMaxSpeechInputLength(){return 4000;}
    public int speak(String text,int queue,Object params,String id){this.id=id;return SUCCESS;}
    public int stop(){return SUCCESS;} public void shutdown(){}
}
