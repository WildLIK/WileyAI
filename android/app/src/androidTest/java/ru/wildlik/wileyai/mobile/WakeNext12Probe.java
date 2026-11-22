package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Debug;
import android.os.SystemClock;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Comparator;
import org.json.JSONArray;
import org.json.JSONObject;
import org.vosk.Recognizer;

/** On-device replay of existing study clips through the actual Vosk front end. */
final class WakeNext12Probe {
    private static final int RATE=16000, BLOCK=2048;
    static String run(Context context) throws Exception {
        Path model=VerifiedModelInstaller.active(context.getFilesDir().toPath().resolve("speech-models"));
        if(model==null)throw new IllegalStateException("Vosk model unavailable");
        File dir=new File(context.getFilesDir(),"wake-study");
        File[] clips=dir.listFiles((folder,name)->name.endsWith(".json") &&
            WakeSampleStore.validId(name.substring(0,name.length()-5)));
        if(clips==null||clips.length<44)throw new IllegalStateException("Expected saved study clips");
        Arrays.sort(clips,Comparator.comparing(File::getName));
        JSONArray rows=new JSONArray();
        long before=Debug.getPss();
        long init=SystemClock.elapsedRealtime();
        long cpu=Debug.threadCpuTimeNanos();
        long recovered=0, buffered=0;
        long loaded,elapsed,peak;
        try(SpeechRuntime.Lease weights=SpeechRuntime.acquire(model)){
            String grammar=WakeVocabulary.grammar(weights.model(),WakePhrase.SHORT);
            elapsed=SystemClock.elapsedRealtime()-init;
            loaded=Debug.getPss();
            for(File meta:clips){
                JSONObject sample=new JSONObject(new String(Files.readAllBytes(meta.toPath()),
                    java.nio.charset.StandardCharsets.UTF_8));
                String id=sample.getString("id");
                if(!meta.getName().equals(id+".json"))throw new IllegalArgumentException("Bad sample ID");
                int count=sample.getInt("samples");
                if(count<8000||count>120*RATE)throw new IllegalArgumentException("Sample length");
                short[] pcm=readClip(dir.toPath().resolve(id+".wav"),count);
                JSONObject row=new JSONObject().put("id",id.substring(0,8)).put("phrase",sample.getString("phrase"))
                    .put("positive","positive".equals(sample.getString("kind"))).put("samples",count);
                int baseline=-1,prefix=-1;
                long spent=0;
                try(Recognizer decoder=new Recognizer(weights.model(),RATE,grammar)){
                    decoder.setWords(true);
                    short[] block=new short[BLOCK];
                    for(int offset=0;offset<count+RATE;offset+=BLOCK){
                        int n=Math.min(count+RATE-offset,BLOCK);
                        int present=Math.max(0,Math.min(count-offset,n));
                        if(present>0)System.arraycopy(pcm,offset,block,0,present);
                        Arrays.fill(block,present,n,(short)0);
                        if(!decoder.acceptWaveForm(block,n))continue;
                        JSONObject result=new JSONObject(decoder.getResult());
                        JSONArray words=result.optJSONArray("result");
                        if(words==null||words.length()==0)continue;
                        double confidence=1;
                        for(int j=0;j<words.length();j++)confidence=Math.min(confidence,words.getJSONObject(j).optDouble("conf",0));
                        int position=offset+n;
                        String text=result.optString("text");
                        if(WakePhrase.matches(WakePhrase.SHORT,text,confidence)||WakePhrase.conversation(WakePhrase.SHORT,text,confidence)){
                            if(baseline<0)baseline=position;
                            if(prefix<0)prefix=position;
                        }else{
                            long start=SystemClock.elapsedRealtimeNanos();
                            WakeFinalPrefix.Match candidate=WakeEngine.recover(words,position);
                            spent+=SystemClock.elapsedRealtimeNanos()-start;
                            if(candidate!=null&&prefix<0&&position<=count){
                                prefix=position;
                                int first=Math.toIntExact(candidate.commandStart());
                                int samples=checkQueue(pcm,position,first);
                                recovered++;
                                buffered+=samples;
                                row.put("rescued",true).put("lag_ms",(position-candidate.end())/16.0)
                                    .put("boundary",first).put("buffered",samples);
                            }
                        }
                        if(baseline>=0&&prefix>=0)break;
                    }
                }
                rows.put(row.put("baseline",baseline).put("prefix",prefix).put("parse_us",spent/1000));
            }
            peak=Debug.getPss();
        }
        return new JSONObject().put("inputs",rows).put("recovered",recovered).put("buffered_samples",buffered)
            .put("initial_pss_kib",before).put("model_pss_kib",loaded).put("final_phase_pss_kib",peak)
            .put("load_ms",elapsed).put("total_ms",SystemClock.elapsedRealtime()-init)
            .put("thread_cpu_ms",(Debug.threadCpuTimeNanos()-cpu)/1000000).put("microphone_opened",false).toString();
    }

    private static short[] readClip(Path path,int count)throws Exception{
        short[] pcm=new short[count];
        for(int offset=0;offset<count;offset+=11*RATE){
            int size=Math.min(count-offset,11*RATE);
            short[] part=AcousticAudio.read(path,offset,size);
            if(part.length!=size)throw new IllegalArgumentException("Truncated WAV");
            System.arraycopy(part,0,pcm,offset,size);
        }
        return pcm;
    }

    private static int checkQueue(short[] pcm,int decision,int first)throws Exception{
        PcmHandoff pipe=new PcmHandoff(RATE*8,RATE*20);
        pipe.append(pcm,decision);
        pipe.activate(first);
        int buffered=pipe.bufferedSamples();
        if(buffered!=decision-first)throw new AssertionError("PCM begin boundary");
        // Simulate live delivery in chunks, while the consumer drains audio accepted at activation.
        short[] block=new short[2048];
        try {
            int offset=first;
            while(offset<decision){
                int n=pipe.read(block,0);
                if(n<=0)throw new AssertionError("missing retained frames");
                for(int k=0;k<n;k++)if(block[k]!=pcm[offset+k])throw new AssertionError("changed samples");
                offset+=n;
            }
            int sent=decision;
            while(sent<pcm.length){
                int next=Math.min(pcm.length,sent+BLOCK);
                pipe.append(Arrays.copyOfRange(pcm,sent,next),next-sent);
                int n=pipe.read(block,0);
                if(n!=next-sent)throw new AssertionError("missing continuation");
                for(int k=0;k<n;k++)if(block[k]!=pcm[sent+k])throw new AssertionError("changed continuation");
                sent=next;
            }
            pipe.seal();
            if(pipe.read(block,0)!=-1||pipe.stats().overflowSamples()!=0)throw new AssertionError("PCM queue state");
        }finally{pipe.close();}
        return buffered;
    }
}
