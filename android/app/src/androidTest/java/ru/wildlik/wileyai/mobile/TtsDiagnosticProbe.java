package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Read the selected configuration, then try a fixed sample; never edits preferences. */
final class TtsDiagnosticProbe {
    static void run(Instrumentation runner, Context context, boolean system) throws Exception {
        runPhrase(runner,context,system,"Проверка озвучивания. Я Уайли.");
    }
    static void runPhrase(Instrumentation runner, Context context, boolean system, String phrase) throws Exception {
        SharedPreferences prefs=context.getSharedPreferences(system ? "c8b-tts-probe" : "wiley-mobile",Context.MODE_PRIVATE);
        LocalVoice[] instance=new LocalVoice[1];
        CountDownLatch initialized=new CountDownLatch(1), finished=new CountDownLatch(1);
        AtomicReference<String> failure=new AtomicReference<>();
        try {
            runner.runOnMainSync(()->{
                instance[0]=new LocalVoice(context,prefs,error->{failure.set(error);initialized.countDown();finished.countDown();});
                instance[0].ready(initialized::countDown);
            });
            if(!initialized.await(20,TimeUnit.SECONDS))throw new AssertionError("tts_init_timeout");
            if(failure.get()!=null)throw new AssertionError("tts_init: "+failure.get());
            runner.runOnMainSync(()->{
                Log.i("WileyTtsProbe","engine_label="+instance[0].engineLabel()+" offline_ru_voices="+instance[0].voices().size());
                instance[0].speakCompleted(phrase,finished::countDown);
            });
            if(!finished.await(30,TimeUnit.SECONDS))throw new AssertionError("tts_completion_timeout");
            if(failure.get()!=null)throw new AssertionError("tts_speak: "+failure.get());
            Log.i("WileyTtsProbe","completed=true");
        } finally { if(instance[0]!=null)runner.runOnMainSync(instance[0]::close); }
    }
}
