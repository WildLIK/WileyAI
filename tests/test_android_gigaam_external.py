"""Exercise the actual external-PCM engine on a JVM with fake Android and ASR."""
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.parametrize("amplitude", [2000, 500])
def test_external_pcm_reaches_gigaam_once_without_prompt(tmp_path, amplitude):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    stubs = {
        'android/Manifest.java': 'package android; public class Manifest { public static class permission { public static final String RECORD_AUDIO="audio"; }}',
        'android/content/Context.java': 'package android.content; public class Context { public Context getApplicationContext(){return this;} public int checkSelfPermission(String x){return 0;} }',
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
            static class Ticket {CompletableFuture<Output> result=CompletableFuture.completedFuture(new Output());}}
          class GigaAmRuntime {volatile float[] received; volatile int calls; void prepare(){}
            GigaAmSession.Ticket recognize(float[] s,int rate,double ms){received=s;calls++;return new GigaAmSession.Ticket();}}
          class NeonWaveMath {static class LevelNormalizer {float observe(double x){return 0;}}}
          class VoiceSpectrum {float[] analyze(short[] b,int n){return new float[0];}}
          class DiagnosticJournal {enum Event {AUDIO_RECORD_COUNT,GIGA_CAPTURE_MS,GIGA_VAD_DISCARDED_SAMPLES,GIGA_LIMIT_DISCARDED_SAMPLES,GIGA_AUDIO_MS,GIGA_DECODE_MS,GIGA_QUEUE_MS,PCM_PEAK_BUFFER_SAMPLES,PCM_DELIVERED_SAMPLES,PCM_ACCEPTED_SAMPLES,PCM_OVERFLOW_SAMPLES,PCM_DISCARDED_SAMPLES}}
          class DiagnosticLog {static void event(DiagnosticJournal.Event e,long v){}}
          class OfflineSpeechEngine {interface Listener {default void speechEnded(long stamp){} default void gigaStage(GigaAmSpeechEngine.Stage stage,long value){} default void level(float f){} default boolean wantsSpectrum(){return false;}
            default void spectrum(float[] f){} default void ready(Runnable r){r.run();} void state(String s);void partial(String s);
            void result(String s);void error(String s);void finished();}}''',
        'ru/wildlik/wileyai/mobile/ExternalProbe.java': '''package ru.wildlik.wileyai.mobile;
          import java.util.concurrent.*;
          public class ExternalProbe {
            public static void main(String[] args) throws Exception {
              PcmHandoff input=new PcmHandoff(20000,20000); short[] wake=new short[500]; input.append(wake,wake.length);
              short[] expected=new short[8192]; for(int i=0;i<expected.length;i++)expected[i]=(short)(2000+i%100);
              input.append(java.util.Arrays.copyOfRange(expected,0,3000),3000); input.activate(500);
              input.append(java.util.Arrays.copyOfRange(expected,3000,expected.length),expected.length-3000); GigaAmRuntime runtime=new GigaAmRuntime();
              GigaAmSpeechEngine engine=new GigaAmSpeechEngine(new android.content.Context(),runtime); CountDownLatch done=new CountDownLatch(1);
              String[] failure={null};int[] prompts={0};
              engine.startFromPcm(3000,new OfflineSpeechEngine.Listener(){
                public void ready(Runnable r){prompts[0]++;r.run();}public void state(String s){if(s.startsWith("Слышу речь"))engine.finish();}public void partial(String s){}
                public void result(String s){}public void error(String s){failure[0]=s;}public void finished(){done.countDown();}
              },input);
              if(!done.await(4,TimeUnit.SECONDS))throw new AssertionError("timeout");
              engine.close();if(failure[0]!=null)throw new AssertionError(failure[0]);
              if(prompts[0]!=0||runtime.calls!=1||runtime.received==null||runtime.received.length!=expected.length)throw new AssertionError("count/prompt");
              for(int i=0;i<expected.length;i++)if(runtime.received[i]!=expected[i]/32768f)throw new AssertionError("missing or duplicate PCM at "+i);
            }
          }''',
    }
    stubs['ru/wildlik/wileyai/mobile/ExternalProbe.java'] = stubs['ru/wildlik/wileyai/mobile/ExternalProbe.java'].replace('2000+i%100', str(amplitude) + '+i%100')
    paths = []
    for rel, code in stubs.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding='utf8')
        paths.append(path)
    source = Path(__file__).resolve().parents[1] / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    paths += [source / name for name in ('PcmChunk.java', 'PcmRingBuffer.java', 'PcmHandoff.java', 'VoiceTelemetry.java', 'GigaAmSpeechEngine.java')]
    p = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, paths)], capture_output=True, text=True, timeout=45)
    assert p.returncode == 0, p.stderr
    p = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.ExternalProbe'], capture_output=True, text=True, timeout=15)
    assert p.returncode == 0, p.stdout + p.stderr
