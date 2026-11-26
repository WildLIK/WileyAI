"""Exercise the actual external-PCM engine on a JVM with fake Android and ASR."""
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.parametrize("amplitude,mode", [(2000, "legacy"), (500, "legacy"),
    (150, "silero"), (150, "endpoint"), (500, "vad-error"), (150, "cancel"),
    (0, "timeout"), (150, "init-error"), (150, "decode-cancel"), (150, "decode-error")])
def test_external_pcm_reaches_gigaam_once_without_prompt(tmp_path, amplitude, mode):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    stubs = {
        'android/Manifest.java': 'package android; public class Manifest { public static class permission { public static final String RECORD_AUDIO="audio"; }}',
        'android/content/Context.java': '''package android.content;
          public class Context { public static final int MODE_PRIVATE=0;
            public Context getApplicationContext(){return this;} public int checkSelfPermission(String x){return 0;}
            public SharedPreferences getSharedPreferences(String name,int mode){return (key,value)->!System.getProperty("probe.mode").equals("legacy");}
            public android.content.res.AssetManager getAssets(){return new android.content.res.AssetManager();}
          }''',
        'android/content/SharedPreferences.java': 'package android.content; public interface SharedPreferences { boolean getBoolean(String k, boolean d); }',
        'android/content/res/AssetManager.java': '''package android.content.res;
          public class AssetManager { public java.io.InputStream open(String p) {
            return new java.io.ByteArrayInputStream(new byte[]{1});
          }}''',
        'com/k2fsa/sherpa/onnx/VadModelConfig.java': '''package com.k2fsa.sherpa.onnx;
          public class VadModelConfig { private final SileroVadModelConfig model=new SileroVadModelConfig();
            public SileroVadModelConfig getSileroVadModelConfig(){return model;}
            public void setSampleRate(int v){if(v!=16000)throw new AssertionError();}
            public void setNumThreads(int v){if(v!=1)throw new AssertionError();}
          }''',
        'com/k2fsa/sherpa/onnx/SileroVadModelConfig.java': '''package com.k2fsa.sherpa.onnx;
          public class SileroVadModelConfig {
            public void setModel(String s){if(!s.endsWith("silero_vad_v5.onnx"))throw new AssertionError();}
            public void setWindowSize(int v){if(v!=512)throw new AssertionError();}
          }''',
        'com/k2fsa/sherpa/onnx/Vad.java': '''package com.k2fsa.sherpa.onnx;
          public class Vad {
            public static int loaded, released;
            private float[] past=new float[64];
            public Vad(android.content.res.AssetManager assets,VadModelConfig cfg) {
              if(System.getProperty("probe.mode").equals("init-error"))throw new IllegalStateException("init");
              loaded++;
            }
            public float compute(float[] block){
              if(System.getProperty("probe.mode").equals("vad-error"))throw new IllegalStateException("inference");
              if(block.length!=576)throw new AssertionError("V5 dimensions");
              for(int i=0;i<64;i++)if(past[i]!=block[i])throw new AssertionError("context");
              System.arraycopy(block,512,past,0,64);
              return block[200]==0?.01f:.9f;
            }
            public void release(){released++;}
          }''',
        'android/content/pm/PackageManager.java': 'package android.content.pm; public class PackageManager { public static final int PERMISSION_GRANTED=0; }',
        'android/media/AudioFormat.java': 'package android.media; public class AudioFormat { public static final int CHANNEL_IN_MONO=1, ENCODING_PCM_16BIT=2; }',
        'android/media/MediaRecorder.java': 'package android.media; public class MediaRecorder { public static class AudioSource { public static final int VOICE_RECOGNITION=1; }}',
        'android/media/AudioRecord.java': '''package android.media; public class AudioRecord {
           public static final int STATE_INITIALIZED=1,RECORDSTATE_RECORDING=3;
           public AudioRecord(int a,int b,int c,int d,int e){throw new AssertionError("unexpected second microphone");}
           public static int getMinBufferSize(int a,int b,int c){return 8192;} public int getState(){return 1;}
           public void startRecording(){} public int getRecordingState(){return 3;} public int read(short[] b,int s,int n){return -1;}
           public void stop(){} public void release(){} }''',
        'android/os/Looper.java': 'package android.os; public class Looper { public static Looper getMainLooper(){return new Looper();} }',
        'android/os/Handler.java': 'package android.os; public class Handler { public Handler(Looper l){} public boolean post(Runnable r){r.run();return true;} }',
        'android/os/SystemClock.java': 'package android.os; public class SystemClock { public static long elapsedRealtime(){return System.nanoTime()/1000000L;} }',
        'android/util/Log.java': 'package android.util; public class Log { public static int i(String a,String b){return 0;} }',
        'ru/wildlik/wileyai/mobile/ModelStubs.java': '''package ru.wildlik.wileyai.mobile;
          import java.util.concurrent.*;
          class GigaAmModel {static final int SAMPLE_RATE=16000;}
          class GigaAmModelManager {static Object activeModel(android.content.Context c){return new Object();}}
          class GigaAmSession {static class Metrics {double decodeMs(){return 1;}double queueMs(){return 1;}} static class Output {boolean stopped(){return false;} String text(){return "ok";}Metrics metrics(){return new Metrics();}}
            static class Ticket {CompletableFuture<Output> result=new CompletableFuture<>(); volatile boolean cancelled;
              void cancel(){cancelled=true;}}}
          class GigaAmRuntime {volatile float[] received; volatile int calls; final CountDownLatch submitted=new CountDownLatch(1);
            volatile GigaAmSession.Ticket first; void prepare(){}
            GigaAmSession.Ticket recognize(float[] s,int rate,double ms){
              received=s;calls++;
              var ticket=new GigaAmSession.Ticket();
              String mode=System.getProperty("probe.mode");
              if(calls!=1||!mode.equals("decode-cancel")){
                if(calls==1&&mode.equals("decode-error"))ticket.result.completeExceptionally(new java.io.IOException("decode failure"));
                else ticket.result.complete(new GigaAmSession.Output());
              }
              if(calls==1){first=ticket;submitted.countDown();}
              return ticket;
            }}
          class NeonWaveMath {static class LevelNormalizer {float observe(double x){return 0;}}}
          class VoiceSpectrum {float[] analyze(short[] b,int n){return new float[0];}}
          class AudioRouteManager {
            static class EffectsSession implements AutoCloseable {public void close(){}}
            static int commandAudioSource(android.content.Context context){throw new AssertionError("PCM handoff must not initialize a new route");}
            static EffectsSession attachEffects(android.content.Context context,android.media.AudioRecord recorder,boolean enabled){
              throw new AssertionError("PCM handoff must reuse the existing capture effects");
            }
          }
          class DiagnosticJournal {enum Event {AUDIO_RECORD_COUNT,GIGA_CAPTURE_MS,GIGA_VAD_DISCARDED_SAMPLES,GIGA_LIMIT_DISCARDED_SAMPLES,GIGA_AUDIO_MS,GIGA_DECODE_MS,GIGA_QUEUE_MS,PCM_PEAK_BUFFER_SAMPLES,PCM_DELIVERED_SAMPLES,PCM_ACCEPTED_SAMPLES,PCM_OVERFLOW_SAMPLES,PCM_DISCARDED_SAMPLES}}
          class DiagnosticLog {static void event(DiagnosticJournal.Event e,long v){}}
          class OfflineSpeechEngine {interface Listener {default void speechEnded(long stamp){} default void gigaStage(GigaAmSpeechEngine.Stage stage,long value){} default void level(float f){} default boolean wantsSpectrum(){return false;}
            default void spectrum(float[] f){} default void ready(Runnable r){r.run();} void state(String s);void partial(String s);
            void result(String s);void error(String s);void finished();}}''',
        'ru/wildlik/wileyai/mobile/ExternalProbe.java': '''package ru.wildlik.wileyai.mobile;
          import java.util.concurrent.*;
          public class ExternalProbe {
            public static void main(String[] args) throws Exception {
              PcmHandoff input=new PcmHandoff(20000,64000); short[] wake=new short[500]; input.append(wake,wake.length);
              String mode=args[0];System.setProperty("probe.mode",mode);
              boolean cancelled=mode.equals("cancel"), noSpeech=mode.equals("timeout")||mode.equals("init-error");
              int amplitude=Integer.parseInt(args[1]);
              boolean endpoint=mode.equals("endpoint");
              short[] expected=new short[endpoint?30000:8192];
              for(int i=0;i<expected.length;i++)expected[i]=(short)(amplitude==0?0:amplitude+i%100);
              if(endpoint) {java.util.Arrays.fill(expected,2048,6144,(short)0);java.util.Arrays.fill(expected,10240,expected.length,(short)0);}
              input.append(java.util.Arrays.copyOfRange(expected,0,3000),3000); input.activate(500);
              input.append(java.util.Arrays.copyOfRange(expected,3000,expected.length),expected.length-3000); GigaAmRuntime runtime=new GigaAmRuntime();
              GigaAmSpeechEngine engine=new GigaAmSpeechEngine(new android.content.Context(),runtime); CountDownLatch done=new CountDownLatch(1);
              String[] failure={null};int[] prompts={0}, results={0};
              if(mode.startsWith("decode-")){
                boolean duringDecode=mode.equals("decode-cancel");
                try {
                  engine.startFromPcm(3000,listener(engine,done,failure,results),input);
                  if(!runtime.submitted.await(3,TimeUnit.SECONDS))throw new AssertionError("not submitted");
                  if(duringDecode)engine.cancel();
                  if(!done.await(1500,TimeUnit.MILLISECONDS))throw new AssertionError("capture still busy after cancellation");
                  if(engine.busy()||results[0]!=0||(failure[0]!=null)==duringDecode)
                    throw new AssertionError("invalid failed/cancelled state");
                  if(duringDecode&&!runtime.first.cancelled)throw new AssertionError("decode ticket still live");
                  PcmHandoff retry=new PcmHandoff(20000,64000);
                  retry.activate(0);retry.append(expected,expected.length);
                  CountDownLatch retryDone=new CountDownLatch(1);failure[0]=null;
                  engine.startFromPcm(3000,listener(engine,retryDone,failure,results),retry);
                  if(!retryDone.await(3,TimeUnit.SECONDS)||failure[0]!=null||results[0]!=1||runtime.calls!=2)
                    throw new AssertionError("next capture did not recover");
                  if(com.k2fsa.sherpa.onnx.Vad.loaded!=2||com.k2fsa.sherpa.onnx.Vad.released!=2)
                    throw new AssertionError("VAD lifecycle");
                } finally {engine.close();}
                return;
              }
              engine.startFromPcm(3000,new OfflineSpeechEngine.Listener(){
                public void ready(Runnable r){prompts[0]++;r.run();}public void state(String s){if(s.startsWith("Слышу речь")){if(cancelled)engine.cancel();else if(!endpoint)engine.finish();}}public void partial(String s){}
                public void result(String s){results[0]++; if(noSpeech&&!s.isEmpty())failure[0]="unexpected transcript";}
                public void error(String s){failure[0]=s;}public void finished(){done.countDown();}
              },input);
              if(!done.await(6,TimeUnit.SECONDS))throw new AssertionError("timeout");
              engine.close();if(failure[0]!=null)throw new AssertionError(failure[0]);
              int opened=com.k2fsa.sherpa.onnx.Vad.loaded;
              if(opened!=(mode.equals("legacy")||mode.equals("init-error")?0:1)||opened!=com.k2fsa.sherpa.onnx.Vad.released)
                throw new AssertionError("VAD lifecycle");
              if(prompts[0]!=0||results[0]!=(cancelled?0:1))throw new AssertionError("result/prompt");
              if(cancelled||noSpeech){if(runtime.calls!=0)throw new AssertionError("unexpected decode");return;}
              var stats=input.stats();if(stats.acceptedSamples()!=stats.deliveredSamples()||stats.overflowSamples()!=0||stats.discardedSamples()!=0)throw new AssertionError("handoff stats");
              if(runtime.calls!=1||runtime.received==null||runtime.received.length!=expected.length)throw new AssertionError("count");
              for(int i=0;i<expected.length;i++)if(runtime.received[i]!=expected[i]/32768f)throw new AssertionError("missing or duplicate PCM at "+i);
            }
            private static OfflineSpeechEngine.Listener listener(GigaAmSpeechEngine engine,CountDownLatch done,String[] failure,int[] results){
              return new OfflineSpeechEngine.Listener(){
                public void state(String s){if(s.startsWith("Слышу речь"))engine.finish();}public void partial(String s){}
                public void result(String s){results[0]++;}
                public void error(String s){failure[0]=s;}public void finished(){done.countDown();}
              };
            }
          }''',
    }
    paths = []
    for rel, code in stubs.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding='utf8')
        paths.append(path)
    source = Path(__file__).resolve().parents[1] / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    paths += [source / name for name in ('PcmChunk.java', 'PcmRingBuffer.java', 'PcmHandoff.java', 'VoiceTelemetry.java', 'GigaAmSpeechEngine.java', 'GigaAmSileroVad.java')]
    p = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, paths)], capture_output=True, text=True, timeout=45)
    assert p.returncode == 0, p.stderr
    p = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.ExternalProbe', mode, str(amplitude)], capture_output=True, text=True, timeout=15)
    assert p.returncode == 0, p.stdout + p.stderr
