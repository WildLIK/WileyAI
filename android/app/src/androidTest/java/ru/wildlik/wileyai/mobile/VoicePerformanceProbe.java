package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.Context;
import android.content.SharedPreferences;
import java.util.EnumMap;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;

/** Benchmarks the installed offline voice with neutral text and isolated preferences. */
final class VoicePerformanceProbe {
    static String run(Instrumentation runner,Context context)throws Exception{
        String name="next3-probe-"+UUID.randomUUID();
        SharedPreferences source=context.getSharedPreferences("wiley-mobile",0);
        SharedPreferences probe=context.getSharedPreferences(name,0);
        probe.edit().putString("offline_engine",source.getString("offline_engine",""))
            .putString("offline_voice",source.getString("offline_voice",""))
            .putFloat("offline_voice_rate",source.getFloat("offline_voice_rate",1))
            .putFloat("offline_voice_pitch",source.getFloat("offline_voice_pitch",1)).apply();
        LocalVoice[] voice={null};
        AtomicReference<String> error=new AtomicReference<>();
        CountDownLatch ready=new CountDownLatch(1);
        JSONArray previous=new JSONArray(),reused=new JSONArray();
        try{
            long began=System.nanoTime();
            runner.runOnMainSync(()->{
                voice[0]=new LocalVoice(context,probe,error::set);
                voice[0].ready(ready::countDown);
            });
            if(!ready.await(12,TimeUnit.SECONDS))throw new AssertionError("TTS initialization unavailable");
            double init=ms(System.nanoTime()-began);
            for(int pair=0;pair<6;pair++){
                for(int step=0;step<2;step++){
                    boolean reuse=(pair+step)%2==1;
                    probe.edit().putBoolean("voice_tts_reuse",reuse).apply();
                    speak(runner,voice[0],"Слушаю.",error); // Same preceding prompt in both arms.
                    (reuse?reused:previous).put(speak(runner,voice[0],"Сейчас ровно полдень.",error));
                }
            }
            CountDownLatch played=new CountDownLatch(1);
            boolean[] staleCompletion={false};
            runner.runOnMainSync(()->voice[0].speakTimed("Это нейтральная проверка отмены озвучивания длинного ответа.",()->staleCompletion[0]=true,stage->{
                if(stage==LocalVoice.Stage.PLAYING){voice[0].stop();played.countDown();}
            }));
            if(!played.await(8,TimeUnit.SECONDS))throw new AssertionError("No playing callback before cancel");
            speak(runner,voice[0],"Готово.",error);
            if(staleCompletion[0])throw new AssertionError("Cancelled speech callback escaped");
            return new JSONObject().put("init_ms",init).put("no_reuse",previous).put("reuse",reused)
                .put("cancel_then_repeat",true).toString();
        }finally{
            if(voice[0]!=null)runner.runOnMainSync(voice[0]::close);
            context.deleteSharedPreferences(name);
        }
    }
    private static JSONObject speak(Instrumentation runner,LocalVoice voice,String text,AtomicReference<String> error)throws Exception{
        CountDownLatch done=new CountDownLatch(1);
        EnumMap<LocalVoice.Stage,Long> value=new EnumMap<>(LocalVoice.Stage.class);
        runner.runOnMainSync(()->voice.speakTimed(text,done::countDown,stage->value.putIfAbsent(stage,System.nanoTime())));
        if(!done.await(12,TimeUnit.SECONDS)||error.get()!=null)throw new AssertionError("Offline speech failed or timed out");
        long request=value.get(LocalVoice.Stage.PREPARE);
        if(!value.containsKey(LocalVoice.Stage.PLAYING)||!value.containsKey(LocalVoice.Stage.SUBMIT))
            throw new AssertionError("Expected speech callbacks missing");
        JSONObject marks=new JSONObject();
        for(var point:value.entrySet())marks.put(point.getKey().name().toLowerCase(java.util.Locale.ROOT),ms(point.getValue()-request));
        return marks;
    }
    private static double ms(long nanos){return Math.round(nanos/1000.0)/1000.0;}
}
