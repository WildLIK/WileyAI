package ru.wildlik.wileyai.mobile;
import android.content.Context;
import android.os.Looper;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Deterministic main-loop boundary: production LocalLlm + session, fake Android/native. */
public class LocalLlmUiProbe {
    static final class Listener implements LocalLlm.Listener {
        int callbacks,finished,done;boolean stopped;
        public void state(String text){callbacks++;}public void partial(String text){callbacks++;}
        public void done(String text,boolean stopped){callbacks++;done++;this.stopped=stopped;}
        public void error(String text){callbacks++;}public void finished(){finished++;}
    }
    public static void main(String[] args)throws Exception {
        if(args[0].equals("response-preferences")){
            var messages=List.of(new LocalChatRepository.Message("user","Как дела?"));
            String ordinary=LocalLlm.prompt(messages);
            String custom=LocalLlm.prompt(messages,"\nПожелание: обращайся на ты.");
            LocalModelSessionProbe.check(!ordinary.contains("обращайся на ты"),"defaults changed");
            LocalModelSessionProbe.check(custom.indexOf("обращайся на ты")<custom.indexOf("<|im_start|>user")
                &&custom.contains("Пожелание: обращайся на ты"),"preferences outside system message");
            LocalModelSessionProbe.check(custom.contains("не утверждай, что выполнила действия"),"lost safety instruction");
            return;
        }
        LocalLlm engine=new LocalLlm(new Context());Listener listener=new Listener();
        engine.generate(Path.of("fake"),"fixed prompt",listener);
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(Looper.pending.size()<3){if(System.nanoTime()>deadline)throw new AssertionError("callback deadline");Thread.yield();}
        LocalModelSessionProbe.check(engine.busy(),"request released before main callback");
        if(args[0].equals("late-stop"))engine.cancel();else engine.close();
        Looper.drain();
        if(args[0].equals("late-stop"))LocalModelSessionProbe.check(listener.done==1&&listener.stopped&&listener.finished==1&&!engine.busy(),"late stop was lost");
        else LocalModelSessionProbe.check(listener.callbacks==0&&listener.finished==0,"closed screen received late callback");
        engine.close();engine.close();LocalLlmRuntime.instance.session.close();LocalLlmRuntime.instance.session.termination().get(3,TimeUnit.SECONDS);
        LocalModelSessionProbe.check(LocalLlmRuntime.nativeApi.live.isEmpty(),"native leak");
        System.out.println("PASS UI "+args[0]);
    }
}
class LocalChatRepository { record Message(String role,String content){} }
class LocalLlmRuntime {
    static final LocalModelSessionProbe.Native nativeApi=new LocalModelSessionProbe.Native();
    static final LocalLlmRuntime instance=new LocalLlmRuntime();
    final LocalModelSession session=new LocalModelSession(nativeApi,()->memory(null),10000,m->{});
    static LocalLlmRuntime get(Context context){return instance;}
    static LocalModelSession.Memory memory(Context context){return new LocalModelSession.Memory(2048L*1048576,8L*1024*1048576,false);}
    static LocalModelSession.Model model(Path p){return LocalModelSessionProbe.A;}
    static void releaseIfCreated(String reason){instance.session.release(reason,false);}
    void profileChanged(){}
}
