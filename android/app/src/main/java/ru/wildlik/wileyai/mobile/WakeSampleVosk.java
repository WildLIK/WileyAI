package ru.wildlik.wileyai.mobile;

import android.content.Context;
import java.io.IOException;
import org.json.JSONArray;
import org.json.JSONObject;
import org.vosk.Recognizer;

/** Replay a voluntarily recorded clip after microphone release. Metadata only. */
final class WakeSampleVosk {
    static JSONObject evaluate(Context context,byte[] pcm,String preset,java.util.function.BooleanSupplier cancelled)
            throws org.json.JSONException {
        JSONObject snapshot=new JSONObject().put("preset",preset).put("status","unavailable");
        try {
            var path=VerifiedModelInstaller.active(context.getFilesDir().toPath().resolve("speech-models"));
            if(path==null)return snapshot;
            try(SpeechRuntime.Lease weights=SpeechRuntime.acquire(path);
                Recognizer decoder=new Recognizer(weights.model(),16000,WakeVocabulary.grammar(weights.model(),preset))){
                decoder.setWords(true);
                short[] block=new short[2048];
                // A finite tail lets Vosk finalize a clip which ended immediately after the word.
                int samples=pcm.length/2;
                for(int at=0;at<samples+16000&&!cancelled.getAsBoolean();at+=block.length){
                    int size=Math.min(block.length,samples+16000-at);
                    for(int i=0;i<size;i++){
                        int pos=at+i;
                        block[i]=pos<samples?(short)((pcm[pos*2]&255)|(pcm[pos*2+1]<<8)):0;
                    }
                    if(!decoder.acceptWaveForm(block,size))continue;
                    JSONObject result=new JSONObject(decoder.getResult());
                    JSONArray words=result.optJSONArray("result");
                    if(words==null||words.length()==0)continue;
                    double confidence=1;
                    for(int i=0;i<words.length();i++)confidence=Math.min(confidence,words.getJSONObject(i).optDouble("conf",0));
                    String phrase=result.optString("text");
                    boolean dialogue=WakePhrase.conversation(preset,phrase,confidence);
                    if(!dialogue&&!WakePhrase.matches(preset,phrase,confidence))continue;
                    double end=words.getJSONObject(words.length()-1).optDouble("end",Double.NaN);
                    if(Double.isFinite(end))snapshot.put("word_end_sample",Math.round(end*16000));
                    return snapshot.put("status","accepted").put("variant",WakePhrase.variant(phrase,dialogue))
                        .put("confidence_milli",Math.round(confidence*1000)).put("decision_sample",at+size)
                        .put("padded_tail",at+size>samples);
                }
                return snapshot.put("status","not_detected");
            }
        }catch(IOException|RuntimeException|LinkageError engineUnavailable){
            return snapshot;
        }
    }
    private WakeSampleVosk() {}
}
