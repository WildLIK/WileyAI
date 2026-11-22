package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Bundle;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import org.vosk.Recognizer;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Synthetic fixtures only; uses installed Vosk and GigaAM but never opens a microphone or executes commands. */
final class WakeAudioProbe {
 private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
 static void run(Context target,Context test,Bundle result)throws Exception {
  Path vosk=VerifiedModelInstaller.active(target.getFilesDir().toPath().resolve("speech-models"));
  check(vosk!=null && GigaAmModelManager.activeModel(target)!=null,"Required local models are unavailable");
  String[] names={"only","music","okay_music","time","pause"};StringBuilder report=new StringBuilder();
  try(SpeechRuntime.Lease weights=SpeechRuntime.acquire(vosk)){
   for(String name:names){
    byte[] bytes;try(InputStream in=test.getAssets().open("wake_b5_"+name+".wav");ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);bytes=out.toByteArray();}
    check(bytes.length>44 && (bytes.length-44)%2==0,"invalid fixture "+name);short[] x=new short[(bytes.length-44)/2];for(int i=0;i<x.length;i++)x[i]=(short)((bytes[44+i*2]&255)|(bytes[45+i*2]<<8));
    long boundary=-1;try(Recognizer wake=new Recognizer(weights.model(),16000,WakeVocabulary.grammar(weights.model(),WakePhrase.SHORT))){wake.setWords(true);short[] chunk=new short[2048];
     for(int at=0;at<x.length+16000;at+=chunk.length){Arrays.fill(chunk,(short)0);if(at<x.length)System.arraycopy(x,at,chunk,0,Math.min(chunk.length,x.length-at));if(!wake.acceptWaveForm(chunk,chunk.length))continue;JSONObject obj=new JSONObject(wake.getResult());JSONArray words=obj.optJSONArray("result");if(words==null || words.length()==0)continue;double confidence=1;for(int j=0;j<words.length();j++)confidence=Math.min(confidence,words.getJSONObject(j).optDouble("conf",0));if(WakePhrase.matches(WakePhrase.SHORT,obj.optString("text"),confidence)){boundary=Math.round(words.getJSONObject(words.length()-1).getDouble("end")*16000);break;}}
    }
    check(boundary>=0&&boundary<x.length,"Vosk did not find wake or boundary outside fixture "+name);
    PcmHandoff pipe=new PcmHandoff(x.length+1,x.length+1);pipe.append(x,x.length);pipe.activate(boundary);
    GigaAmSpeechEngine engine=new GigaAmSpeechEngine(target,GigaAmRuntime.get(target));CountDownLatch done=new CountDownLatch(1);AtomicReference<String> answer=new AtomicReference<>(""),failure=new AtomicReference<>("");
    engine.startFromPcm(15000,new OfflineSpeechEngine.Listener(){public void state(String s){}public void partial(String s){}public void result(String s){answer.set(s);}public void error(String s){failure.set(s);}public void finished(){done.countDown();}},pipe);
    long deadline=SystemClock.elapsedRealtime()+10000;while(pipe.bufferedSamples()>0&&SystemClock.elapsedRealtime()<deadline)Thread.sleep(10);check(pipe.bufferedSamples()==0,"PCM queue did not drain "+name);engine.finish();check(done.await(35,TimeUnit.SECONDS),"GigaAM timeout "+name);engine.close();check(failure.get().isEmpty(),"GigaAM error "+name);
    String text=answer.get().toLowerCase(Locale.ROOT);boolean expected=name.equals("only")?!text.contains("включ")&&!text.contains("музык"):name.equals("time")?text.contains("времен"):text.contains("включ")&&text.contains("музык");
    report.append(name).append(" wake=ok command=").append(expected?"ok":"missing").append(';');result.putString("wake_audio",report.toString());check(expected,"Expected command not recognized in "+name);
   }
  }
 }
 private WakeAudioProbe(){}
}
