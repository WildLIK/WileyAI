package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Debug;
import android.util.Log;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Owner-run device probe. No preferences, history or Android tools are changed. */
final class LocalLlmExtendedProbe {
    private static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    static void run(Context context) throws Exception {
        Path path=LlmModels.readActive(context.getFilesDir().toPath().resolve("llm-models"));
        check(path!=null,"Локальная модель не установлена");
        LocalLlmRuntime runtime=LocalLlmRuntime.get(context);
        LocalModelSession session=runtime.session;
        LocalModelSession.Model model=LocalLlmRuntime.model(path);
        session.maintenance("extended_start",()->{}).get(100,TimeUnit.SECONDS);
        session.idleTimeout(60000);
        try {
            long before=Debug.getPss();
            String prompt=LocalLlm.prompt(List.of(new LocalChatRepository.Message("user","Сколько будет 2+2? Кратко.")));
            LocalModelSession.Output first=session.generate(model,prompt,null,cold->{},text->{}).result.get(100,TimeUnit.SECONDS);
            check(first.metrics().cold()&&!first.stopped(),"Первый запрос должен быть холодным");
            long cold=Debug.getPss();
            LocalModelSession.Output warm=session.generate(model,prompt,null,coldState->{},text->{}).result.get(100,TimeUnit.SECONDS);
            check(!warm.metrics().cold()&&warm.metrics().loads()==first.metrics().loads(),"Повторная загрузка весов");
            long warmed=Debug.getPss();
            CountDownLatch partial=new CountDownLatch(1),release=new CountDownLatch(1);
            String longPrompt=LocalLlm.prompt(List.of(new LocalChatRepository.Message("user","Напиши подробную историю о путешествии по морю.")));
            LocalModelSession.Ticket ticket=session.generate(model,longPrompt,null,coldState->{},text->{
                partial.countDown();try { release.await(10,TimeUnit.SECONDS); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            });
            try { check(partial.await(90,TimeUnit.SECONDS),"Нет частичного ответа для проверки отмены");ticket.cancel(); }
            finally { release.countDown(); }
            LocalModelSession.Output cancelled=ticket.result.get(100,TimeUnit.SECONDS);
            check(cancelled.stopped(),"Отмена не подтверждена");
            LocalModelSession.Output resumed=session.generate(model,prompt,null,coldState->{},text->{}).result.get(100,TimeUnit.SECONDS);
            check(!resumed.stopped()&&!resumed.metrics().cold()&&resumed.metrics().loads()==first.metrics().loads(),"Повтор после отмены");
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(80);
            while (System.nanoTime()<deadline) {
                LocalModelSession.Metrics m=session.latest();
                if (m!=null&&m.result().equals("unloaded")&&m.unloadReason().equals("idle")) break;
                Thread.sleep(250);
            }
            LocalModelSession.Metrics idle=session.latest();
            check(idle!=null&&idle.result().equals("unloaded")&&idle.unloadReason().equals("idle"),"Выгрузка по простою не произошла");
            long unloaded=Debug.getPss();
            LocalModelSession.Output after=session.generate(model,prompt,null,coldState->{},text->{}).result.get(100,TimeUnit.SECONDS);
            check(after.metrics().cold()&&after.metrics().loads()==first.metrics().loads()+1,"Нет холодной загрузки после простоя");
            Log.i("WileyC8Probe","pss_kib_before="+before+" pss_kib_cold="+cold+" pss_kib_warm="+warmed+" pss_kib_idle="+unloaded+" cancel_stopped=true reuse_after_cancel=true idle_60s=true reload_cold=true");
        } finally {
            session.maintenance("extended_done",()->{}).get(100,TimeUnit.SECONDS);
            runtime.profileChanged();
        }
    }
}
