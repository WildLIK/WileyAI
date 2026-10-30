package ru.wildlik.wileyai.mobile;

import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** Android-only model contract. No provider may execute a tool itself. */
interface BrainProvider extends AutoCloseable {
    enum Kind { LOCAL, DIRECT_CLOUD, ACCOUNT_OAUTH, OFFICIAL_API, REMOTE_GATEWAY }
    record Call(String id,String name,String arguments){}
    record Completion(String text,List<Call> calls,List<Map<String,Object>> continuation){Completion(String text,List<Call> calls){this(text,calls,List.of());}}
    final class Cancellation {
        private final AtomicBoolean cancelled=new AtomicBoolean();private volatile Runnable abort=()->{};
        boolean cancelled(){return cancelled.get();}void check(){if(cancelled())throw new IllegalStateException("Запрос отменён");}
        void onCancel(Runnable action){abort=action;if(cancelled())action.run();}
        void cancel(){cancelled.set(true);abort.run();}
    }
    Kind kind();boolean nativeTools();
    Completion complete(List<Map<String,Object>> messages,List<AndroidTools.Tool> tools,boolean planning,Cancellation cancellation,Consumer<String> status)throws Exception;
    default void close(){}
}
