package ru.wildlik.wileyai.mobile;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** Real production JNI bridge with fake llama symbols, on the host JVM only. */
public final class C8NativeProbe {
    static native long[] stats();
    static void check(boolean v){if(!v)throw new AssertionError();}
    static byte[] bytes(String s){return s.getBytes(StandardCharsets.UTF_8);}
    static long model(String path)throws Exception{long h=LocalLlmNative.create();try{LocalLlmNative.load(h,path);return h;}catch(Throwable e){LocalLlmNative.close(h);throw e;}}
    static void waitNative(int stage)throws Exception{long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);while(stats()[6]!=stage){if(System.nanoTime()>end)throw new AssertionError("native deadline");Thread.yield();}}
    static void request(long h,String grammar,char expected)throws Exception{
        LocalLlmNative.prepare(h);if(grammar!=null)LocalLlmNative.grammar(h,bytes(grammar));LocalLlmNative.begin(h,bytes("prompt"));
        check(LocalLlmNative.next(h)[0]==expected);check(LocalLlmNative.next(h)==null);check(LocalLlmNative.timings(h).length==3);LocalLlmNative.finish(h);
    }
    public static void main(String[] args)throws Exception{
        check(LocalLlmNative.supported());
        switch(args[0]){
            case "reuse"->{long h=model("ok");request(h,null,'G');request(h,"root ::= \"x\"",'J');request(h,null,'G');check(stats()[0]==1&&stats()[2]==3&&stats()[3]==3);LocalLlmNative.close(h);LocalLlmNative.close(h);LocalLlmNative.cancel(h);}
            case "invalid"->{long h=model("ok");LocalLlmNative.close(h);try{LocalLlmNative.prepare(h);throw new AssertionError();}catch(IOException expected){}try{model("bad");throw new AssertionError();}catch(IOException expected){}long fresh=model("ok");check(fresh!=h);request(fresh,null,'G');LocalLlmNative.close(fresh);}
            case "grammar-error"->{long h=model("ok");LocalLlmNative.prepare(h);try{LocalLlmNative.grammar(h,bytes("bad"));throw new AssertionError();}catch(IOException expected){}LocalLlmNative.finish(h);request(h,null,'G');LocalLlmNative.close(h);}
            default->{
                boolean load=args[0].equals("cancel-load"),close=args[0].equals("close-inflight");long h=LocalLlmNative.create();
                if(!load){LocalLlmNative.load(h,"slow_decode");LocalLlmNative.prepare(h);}
                AtomicReference<Throwable> failure=new AtomicReference<>();Thread worker=new Thread(()->{try{if(load)LocalLlmNative.load(h,"slow_load");else LocalLlmNative.begin(h,bytes("prompt"));}catch(Throwable t){failure.set(t);}});worker.start();waitNative(load?1:2);
                if(close)LocalLlmNative.close(h);else LocalLlmNative.cancel(h);worker.join(3000);check(!worker.isAlive()&&failure.get() instanceof IOException);
                if(!load&&!close){LocalLlmNative.finish(h);request(h,null,'G');check(stats()[0]==1);}
                LocalLlmNative.close(h);LocalLlmNative.close(h);
            }
        }
        long[] values=stats();check(values[4]==0&&values[5]==0&&values[0]==values[1]&&values[2]==values[3]);
        System.out.println("PASS JNI "+args[0]);
    }
}
