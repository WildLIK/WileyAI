"""Wake -> shared PCM handoff with deterministic fake microphone and recognizer."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_wake_keeps_same_capture_until_consumer_closes(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    stubs = {
        'android/Manifest.java': 'package android; public class Manifest { public static class permission { public static final String RECORD_AUDIO="audio"; }}',
        'android/content/Context.java': 'package android.content; public class Context { public Context getApplicationContext(){return this;} public int checkSelfPermission(String s){return 0;} }',
        'android/content/pm/PackageManager.java': 'package android.content.pm; public class PackageManager { public static final int PERMISSION_GRANTED=0; }',
        'android/os/Looper.java': 'package android.os; public class Looper { public static Looper getMainLooper(){return new Looper();} }',
        'android/os/Handler.java': 'package android.os; public class Handler { public Handler(Looper l){} public boolean post(Runnable r){r.run();return true;} }',
        'android/os/SystemClock.java': 'package android.os; public class SystemClock { public static long elapsedRealtime(){return 100;} public static long elapsedRealtimeNanos(){return 100000000;} }',
        'android/util/Log.java': 'package android.util; public class Log {public static int i(String a,String b){return 0;}}',
        'android/media/AudioFormat.java': 'package android.media; public class AudioFormat { public static final int CHANNEL_IN_MONO=1, ENCODING_PCM_16BIT=2; }',
        'android/media/MediaRecorder.java': 'package android.media; public class MediaRecorder { public static class AudioSource { public static final int VOICE_RECOGNITION=1; }}',
        'android/media/AudioRecord.java': '''package android.media; public class AudioRecord {
            public static final int STATE_INITIALIZED=1,RECORDSTATE_RECORDING=3;public static int count=0;private int reads;private volatile boolean stopped;
            public AudioRecord(int a,int b,int c,int d,int e){count++;} public static int getMinBufferSize(int a,int b,int c){return 8192;}
            public int getState(){return 1;}public void startRecording(){}public int getRecordingState(){return 3;}
            public int read(short[] b,int off,int n){if(reads<2){int base=reads++*2048;for(int i=0;i<2048;i++)b[i]=(short)(base+i);return 2048;}
                while(!stopped){try{Thread.sleep(5);}catch(Exception e){break;}}throw new IllegalStateException();}
            public void stop(){stopped=true;}public void release(){} }''',
        'org/json/JSONObject.java': '''package org.json; public class JSONObject {public JSONObject(String s){} public JSONArray optJSONArray(String s){return new JSONArray();}
          public String optString(String s){return "вайли";}public double optDouble(String s,double fallback){return s.equals("end")?0.03125:1.0;}}''',
        'org/json/JSONArray.java': 'package org.json; public class JSONArray {public int length(){return 1;}public JSONObject getJSONObject(int i){return new JSONObject("");}}',
        'org/vosk/Recognizer.java': '''package org.vosk; public class Recognizer implements AutoCloseable {
          public Recognizer(Object m,int s,String g){} public void setWords(boolean b){}public boolean acceptWaveForm(short[] b,int n){return true;}
          public String getResult(){return "{}";}public void close(){} }''',
        'ru/wildlik/wileyai/mobile/WakeStubs.java': '''package ru.wildlik.wileyai.mobile; import java.nio.file.Path;
          class SpeechRuntime {static Lease acquire(Path p){return new Lease();}static class Lease implements AutoCloseable {Object model(){return new Object();}public void close(){}}}
          class WakeVocabulary {static String grammar(Object m,String p){return "";}}
          class H2Shadow {
            static int samples,accepted;
            static void feed(long id,long first,short[] b,int n){samples+=n;}
            static void end(long id){}
            static void voskAccepted(){accepted++;}
          }
          class DiagnosticJournal {enum Event {WAKE_START,AUDIO_RECORD_COUNT,WAKE_READY,WAKE_READ_SAMPLES,WAKE_DECODER_FINALS,WAKE_REJECTED_FINALS,WAKE_DETECTION_SAMPLE,WAKE_DETECTION_LAG_MS,PCM_BOUNDARY_SAMPLE,PCM_BUFFERED_SAMPLES,WAKE_STOP_REASON,WAKE_PREFIX_ENABLED,WAKE_PREFIX_RECOVERY_US}}
          class DiagnosticLog {static void event(DiagnosticJournal.Event e,long v){}}
          class AcousticDiagnostics {
            static AcousticDiagnostics active; int samples, candidates;
            static AcousticDiagnostics current(){return active;} boolean capturingInput(){return true;}
            void feed(android.media.AudioRecord mic,long epoch,long at,short[] data,int n,String grammar,String preset){samples+=n;}
            void partial(org.vosk.Recognizer r,long id){}
            boolean candidate(long id,WakeActivation e,String g,String p,org.json.JSONObject j,String reason,double conf,long n,long us){candidates++;return false;}
            void captureEnd(long id,int reason){} boolean suppresses(){return false;} void stop(String reason){}
          }''',
        'ru/wildlik/wileyai/mobile/WakeHandoffProbe.java': '''package ru.wildlik.wileyai.mobile;
          import java.nio.file.Paths;import java.util.concurrent.*;import java.util.concurrent.atomic.*;
          public class WakeHandoffProbe {public static void main(String[] args)throws Exception{
            WakeEngine wake=new WakeEngine(new android.content.Context());AtomicReference<Throwable> fail=new AtomicReference<>();
            WakeActivation.Gate gate=new WakeActivation.Gate();
            WakeActivation first=new WakeActivation(1,100,2,false,750,50), second=new WakeActivation(2,120,3,false,900,60);
            if(!gate.reserve(first)||!gate.waiting()||gate.reserve(second)||gate.matches(2)||!gate.matches(1)||gate.take()!=first
               ||gate.waiting()||!gate.reserve(second)||gate.take()!=second)throw new AssertionError("window claim and expiry");
            for(int cycle=0;cycle<3;cycle++){ CountDownLatch consumed=new CountDownLatch(1), idle=new CountDownLatch(1);
            if(cycle==2)AcousticDiagnostics.active=new AcousticDiagnostics();
            wake.start(Paths.get("fake"),WakePhrase.SHORT,()->{},true,(event,pcm)->{
              if(event.id()<=0||event.lagMillis()!=96||event.variant()!=1||event.confidenceMilli()!=1000||event.conversation())
                throw new AssertionError("candidate metadata");
              new Thread(()->{try{short[] actual=new short[3596], buf=new short[777];int offset=0;while(offset<actual.length){int n=pcm.read(buf,2000);if(n<=0)throw new AssertionError("missing PCM");System.arraycopy(buf,0,actual,offset,n);offset+=n;}
                for(int i=0;i<actual.length;i++)if(actual[i]!=(short)(i+500))throw new AssertionError("PCM mismatch "+i);
              }catch(Throwable t){fail.set(t);}finally{pcm.close();consumed.countDown();}}).start();
            },msg->fail.set(new AssertionError(msg)),()->idle.countDown());
            if(!consumed.await(5,TimeUnit.SECONDS))throw new AssertionError("consumer timeout");wake.pause(()->{});
            if(!idle.await(5,TimeUnit.SECONDS))throw new AssertionError("capture not released");
            if(fail.get()!=null)throw new AssertionError(fail.get());}
            wake.close();if(android.media.AudioRecord.count!=3)throw new AssertionError("capture lifecycle");
            if(H2Shadow.samples!=3*2048 || H2Shadow.accepted!=3)throw new AssertionError("observer must not consume handoff tail");
            if(AcousticDiagnostics.active.samples!=4096||AcousticDiagnostics.active.candidates!=1)
              throw new AssertionError("acoustic tap must see the same capture and the handoff tail");
          }}''',
    }
    paths = []
    for name, code in stubs.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding='utf8')
        paths.append(path)
    src = Path(__file__).resolve().parents[1] / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    paths += [src / x for x in ('PcmRingBuffer.java', 'PcmHandoff.java', 'VoiceTelemetry.java', 'WakePhrase.java', 'WakeActivation.java', 'WakeFinalPrefix.java', 'WakeEngine.java')]
    result = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, paths)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.WakeHandoffProbe'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_wake_asr_homophone_routes_only_a_complete_command(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    root = Path(__file__).resolve().parents[1]
    src = root / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    paths = [src / x for x in ('WakePhrase.java', 'PhoneCommands.java', 'MediaCommands.java', 'SpokenNames.java')]
    paths.append(root / 'tests/android/WakeConfusableProbe.java')
    result = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, paths)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.WakeConfusableProbe'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
