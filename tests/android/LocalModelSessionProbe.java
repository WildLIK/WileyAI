package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Host JVM only: exercises production lifecycle with fake native resources, never phone actions. */
public final class LocalModelSessionProbe {
    static final LocalModelSession.Model A=new LocalModelSession.Model("A|1","A"), B=new LocalModelSession.Model("B|1","B");
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    static void await(CountDownLatch latch)throws Exception{check(latch.await(3,TimeUnit.SECONDS),"deadline");}
    static final class Memory implements LocalModelSession.MemoryReader {
        volatile long available=2048L*1048576;volatile boolean low;
        public LocalModelSession.Memory read(){return new LocalModelSession.Memory(available,8L*1024*1048576,low);}
    }
    static final class Resource { boolean loaded,context;AtomicBoolean stopped=new AtomicBoolean();String grammar,prompt;int piece; }
    static final class Native implements LocalModelSession.Backend {
        final Map<Long,Resource> live=new ConcurrentHashMap<>();final List<String> order=Collections.synchronizedList(new ArrayList<>());
        long sequence;int loads,creates,contexts,begins,closes,finishes,maxLive;volatile String fail="";
        volatile boolean blockLoad,blockNext,blockClose;volatile byte[][] pieces;
        CountDownLatch entered=new CountDownLatch(1),released=new CountDownLatch(1),freed=new CountDownLatch(1),closing=new CountDownLatch(1);
        final AtomicInteger inside=new AtomicInteger();
        Resource resource(long h){Resource r=live.get(h);check(r!=null,"freed handle used");return r;}
        void failure(String phase)throws IOException{if(fail.equals(phase)){fail="";throw new IOException("fake "+phase);}}
        public long create()throws IOException{failure("create");Resource r=new Resource();long h=++sequence;live.put(h,r);creates++;maxLive=Math.max(maxLive,live.size());check(maxLive==1,"multiple models");return h;}
        public void load(long h,String path)throws IOException{
            inside.incrementAndGet();try{failure("load");Resource r=resource(h);if(blockLoad){entered.countDown();while(!r.stopped.get())Thread.yield();throw new IOException("load cancelled");}r.loaded=true;loads++;order.add("load:"+path);}finally{inside.decrementAndGet();}
        }
        public void prepare(long h)throws IOException{failure("prepare");Resource r=resource(h);check(r.loaded&&!r.context,"dirty context");r.context=true;r.grammar=null;r.piece=0;r.stopped.set(false);contexts++;}
        public void grammar(long h,byte[] grammar)throws IOException{failure("grammar");resource(h).grammar=new String(grammar,StandardCharsets.UTF_8);}
        public void begin(long h,byte[] prompt)throws IOException{failure("begin");Resource r=resource(h);check(r.context,"missing context");r.prompt=new String(prompt,StandardCharsets.UTF_8);begins++;order.add("begin:"+r.prompt);}
        public byte[] next(long h)throws IOException{
            inside.incrementAndGet();try{failure("next");Resource r=resource(h);
                if(blockNext){entered.countDown();while(!r.stopped.get()&&released.getCount()!=0)Thread.yield();}
                if(r.stopped.get())return null;
                if(pieces!=null)return r.piece<pieces.length?pieces[r.piece++]:null;
                if(r.piece++>0)return null;
                return (r.grammar==null?r.prompt:"{\"steps\":[],\"reply\":\"ok\"}").getBytes(StandardCharsets.UTF_8);
            }finally{inside.decrementAndGet();}
        }
        public long[] timings(long h){resource(h);return new long[]{100,200,300};}
        public void finish(long h){Resource r=resource(h);r.context=false;r.grammar=null;finishes++;if(fail.equals("finish")){fail="";throw new IllegalStateException("finish");}}
        public void cancel(long h){resource(h).stopped.set(true);}
        public void close(long h){check(inside.get()==0,"close during load/generate");Resource r=resource(h);if(blockClose){closing.countDown();try{await(released);}catch(Exception e){throw new RuntimeException(e);}}check(live.remove(h,r),"double free");closes++;order.add("close");freed.countDown();}
    }
    static LocalModelSession make(Native n,Memory m,long idle){return new LocalModelSession(n,m,idle,x->{});}
    static LocalModelSession.Ticket ask(LocalModelSession s,LocalModelSession.Model model,String prompt,String grammar){return s.generate(model,prompt,grammar,cold->{},text->{});}
    static LocalModelSession.Output done(LocalModelSession.Ticket t)throws Exception{return t.result.get(3,TimeUnit.SECONDS);}
    static void close(LocalModelSession s)throws Exception{s.close();s.close();s.termination().get(3,TimeUnit.SECONDS);}
    static void failed(LocalModelSession.Ticket t)throws Exception{try{done(t);throw new AssertionError("failure expected");}catch(ExecutionException expected){}}
    public static void main(String[] args)throws Exception{
        String test=args[0];Native n=new Native();Memory m=new Memory();LocalModelSession s=make(n,m,test.equals("idle")?40:10000);
        try {
            switch(test){
                case "reuse-json-independent"->{
                    var one=done(ask(s,A,"first",null));var two=done(ask(s,A,"second","root ::= \"json\""));var three=done(ask(s,A,"third",null));
                    check(one.text().equals("first")&&two.text().startsWith("{")&&three.text().equals("third"),"prompt or grammar leaked");
                    check(n.loads==1&&n.begins==3&&n.contexts==3&&n.finishes==3&&n.closes==0,"reuse counts");
                    check(one.metrics().cold()&&!two.metrics().cold()&&!three.metrics().cold(),"cold/warm");
                    check(three.metrics().firstTokenMs()>=0&&three.metrics().ramBefore()>0&&!three.metrics().safeLine().contains("third"),"diagnostics privacy");
                }
                case "idle"->{done(ask(s,A,"first",null));await(n.freed);check(n.closes==1,"idle close");done(ask(s,A,"again",null));check(n.loads==2,"cold after idle");}
                case "model-change"->{done(ask(s,A,"a",null));done(ask(s,B,"b",null));done(ask(s,new LocalModelSession.Model("B|2","B"),"updated",null));check(n.loads==3&&n.closes==2&&n.maxLive==1,"model identity");}
                case "pressure-idle"->{done(ask(s,A,"a",null));s.release("memory_pressure",true);await(n.freed);m.low=true;failed(ask(s,A,"no ram",null));check(n.loads==1,"low memory load");m.low=false;done(ask(s,A,"recovered",null));check(n.loads==2,"recovered");}
                case "pressure-active"->{n.blockNext=true;var t=ask(s,A,"active",null);await(n.entered);m.low=true;s.release("memory_pressure",true);check(done(t).stopped(),"pressure cancellation");await(n.freed);check(n.closes==1,"pressure close");}
                case "memory-after"->{var t=s.generate(A,"a",null,cold->{},text->m.available=100);done(t);check(n.closes==1&&n.live.isEmpty(),"post-generation memory gate");}
                case "cancel-reuse"->{n.blockNext=true;var t=ask(s,A,"old",null);await(n.entered);t.cancel();var cancelled=done(t);check(cancelled.stopped()&&cancelled.metrics().cancellationReason()==1,"stop flag and reason");n.blockNext=false;check(done(ask(s,A,"new",null)).text().equals("new"),"reuse after cancellation");check(n.loads==1&&n.closes==0,"cancel must retain healthy weights");}
                case "cancel-load"->{n.blockLoad=true;var t=ask(s,A,"old",null);await(n.entered);t.cancel();check(done(t).stopped(),"load cancelled");check(n.live.isEmpty(),"partial load released");n.blockLoad=false;done(ask(s,A,"new",null));check(n.loads==1,"recover failed cold load");}
                case "parallel"->{n.blockNext=true;var first=ask(s,A,"one",null);await(n.entered);var second=ask(s,A,"two",null);check(n.begins==1,"no concurrent generation");n.released.countDown();check(done(first).text().equals("one")&&done(second).text().equals("two"),"serial results");check(n.loads==1&&n.contexts==2,"one copy");}
                case "queued-cancel"->{n.blockNext=true;var first=ask(s,A,"one",null);await(n.entered);var second=ask(s,A,"never",null);second.cancel();n.released.countDown();done(first);check(done(second).stopped()&&n.begins==1,"queued cancellation");}
                case "late-cancel"->{var old=ask(s,A,"one",null);done(old);n.blockNext=true;var current=ask(s,A,"two",null);await(n.entered);old.cancel();check(!n.live.values().iterator().next().stopped.get(),"late abort affected new request");current.cancel();check(done(current).stopped()&&n.loads==1,"current cancellation");}
                case "switch-active"->{n.blockNext=true;var first=ask(s,A,"old",null);await(n.entered);var second=ask(s,B,"new",null);check(done(first).stopped(),"old request invalidated");n.blockNext=false;n.released.countDown();check(done(second).text().equals("new")&&n.loads==2,"new model handle");}
                case "close-service"->{n.blockNext=true;var t=ask(s,A,"active",null);await(n.entered);s.close();s.close();check(done(t).stopped(),"service cancellation");s.termination().get(3,TimeUnit.SECONDS);check(n.live.isEmpty()&&n.closes==1,"service resources");failed(ask(s,A,"closed",null));}
                case "owner-reopen"->{done(ask(s,A,"a",null));s.release("owner_closed",false);s.release("owner_closed",false);s.release("controller_closed",false);await(n.freed);done(ask(s,A,"reopen",null));check(n.loads==2&&n.closes==1,"reopen after repeated owner close");}
                case "stress"->{
                    for(int i=0;i<50;i++) {
                        var one=ask(s,A,"a"+i,null);var two=ask(s,A,"b"+i,i%2==0?"grammar":null);
                        if(i%3==0)two.cancel();
                        done(one);done(two);
                        if(i%5==0)s.release("memory_pressure",false);
                    }
                    check(n.maxLive==1,"stress duplicated model");
                }
                case "idle-active"->{done(ask(s,A,"a",null));s.idleTimeout(80);n.blockNext=true;var t=ask(s,A,"active",null);await(n.entered);check(!n.freed.await(150,TimeUnit.MILLISECONDS),"idle freed active handle");t.cancel();done(t);await(n.freed);check(n.loads==1,"warm request");}
                case "ui-nonblocking"->{done(ask(s,A,"a",null));n.blockClose=true;s.release("manual",false);await(n.closing);var queued=ask(s,A,"cancel",null);queued.cancel();n.released.countDown();check(done(queued).stopped(),"request API blocked on unload");}
                case "probe-exclusive"->{done(ask(s,A,"a",null));s.probe(B,new AtomicBoolean());check(n.loads==2&&n.closes==2&&n.maxLive==1,"probe duplicated cache");done(ask(s,A,"back",null));check(n.loads==3,"after probe");}
                case "probe-cancel"->{s.probe(B,new AtomicBoolean(true));throw new AssertionError("cancelled probe");}
                case "utf8"->{byte[] utf="Привет".getBytes(StandardCharsets.UTF_8);n.pieces=new byte[][]{Arrays.copyOfRange(utf,0,1),Arrays.copyOfRange(utf,1,utf.length)};check(done(ask(s,A,"x",null)).text().equals("Привет"),"UTF8 chunks");}
                default->{check(test.startsWith("error-"),"unknown case");n.fail=test.substring(6);failed(ask(s,A,"bad","grammar"));check(n.live.isEmpty(),"poisoned model retained");check(done(ask(s,A,"good",null)).text().equals("good"),"error recovery");}
            }
        }catch(ExecutionException|CancellationException expected){check(test.equals("probe-cancel"),"unexpected exception: "+expected);}
        finally{n.released.countDown();close(s);}
        check(n.live.isEmpty(),"native leak");System.out.println("PASS "+test);
    }
}
