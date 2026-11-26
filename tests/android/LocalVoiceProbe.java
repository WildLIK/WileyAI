package ru.wildlik.wileyai.mobile;
import android.content.*;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

public final class LocalVoiceProbe {
    static final class Prefs implements SharedPreferences, SharedPreferences.Editor {
        final Map<String,String> values=new HashMap<>();
        public String getString(String k,String d){return values.getOrDefault(k,d);} public float getFloat(String k,float d){return d;}
        public Editor edit(){return this;} public Editor putString(String k,String v){values.put(k,v);return this;}
        public Editor remove(String k){values.remove(k);return this;} public void apply(){}
    }
    static void check(boolean v){if(!v)throw new AssertionError();}
    public static void main(String[] args){
        Prefs p=new Prefs(); List<String> errors=new ArrayList<>(); AtomicInteger done=new AtomicInteger();
        p.values.put("offline_engine","disabled");
        LocalVoice v=new LocalVoice(new Context(),p,errors::add);v.speakCompleted("test",done::incrementAndGet);Looper.drain();
        check(errors.size()==1 && errors.get(0).contains("«Системный»"));check(done.get()==1);check(p.getString("offline_engine","").equals("disabled"));
        errors.clear();
        AtomicInteger refreshed=new AtomicInteger();
        v.inspect(refreshed::incrementAndGet);Looper.drain();
        check(refreshed.get()==1 && v.voices().isEmpty() && errors.isEmpty());
        v.reload(refreshed::incrementAndGet);Looper.drain();
        check(refreshed.get()==2 && v.voices().isEmpty() && errors.isEmpty());
        errors.clear();v.selectEngine("",()->{});Looper.drain();check(TextToSpeech.last.engine==null && p.getString("offline_engine","missing").equals(""));
        v.speakCompleted("first",done::incrementAndGet);String old=TextToSpeech.last.id;v.stop();
        List<LocalVoice.Stage> stages=new ArrayList<>();
        v.speakTimed("second",done::incrementAndGet,stages::add);String current=TextToSpeech.last.id;
        check(TextToSpeech.last.voiceLists==1&&TextToSpeech.last.voiceSelections==1);
        TextToSpeech.last.listener.onAudioAvailable(old,new byte[]{1});
        TextToSpeech.last.listener.onAudioAvailable(current,new byte[]{1});
        TextToSpeech.last.listener.onAudioAvailable(current,new byte[]{2});
        TextToSpeech.last.listener.onError(old);Looper.drain();check(errors.isEmpty() && done.get()==1);
        TextToSpeech.last.listener.onStart(current);TextToSpeech.last.listener.onDone(current);Looper.drain();check(done.get()==2);
        check(stages.equals(List.of(LocalVoice.Stage.PREPARE,LocalVoice.Stage.SUBMIT,LocalVoice.Stage.FIRST_AUDIO,LocalVoice.Stage.PLAYING)));
        v.speakCompleted("third",done::incrementAndGet);String third=TextToSpeech.last.id;TextToSpeech.last.listener.onStop(third,true);Looper.drain();check(done.get()==3);
        v.select("missing"); TextToSpeech.noVoices=true;v.speakCompleted("missing",done::incrementAndGet);check(errors.size()==1 && done.get()==4);
        v.close();System.out.println("LocalVoice fake tests passed");
    }
}
