package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.nio.*;
import java.nio.charset.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

/** One process-wide owner. Only the worker touches native resources, except atomic abort. */
final class LocalModelSession implements AutoCloseable {
    static final long RESERVE = 768L * 1048576;
    record Model(String identity, String path) {}
    record Memory(long available, long total, boolean low) {
        boolean sufficient() { return !low && available >= RESERVE; }
    }
    interface MemoryReader { Memory read() throws IOException; }
    interface Backend {
        long create() throws IOException;
        void load(long handle, String path) throws IOException;
        void prepare(long handle) throws IOException;
        void grammar(long handle, byte[] grammar) throws IOException;
        void begin(long handle, byte[] prompt) throws IOException;
        byte[] next(long handle) throws IOException;
        long[] timings(long handle);
        void finish(long handle);
        void cancel(long handle);
        void close(long handle);
    }
    record Metrics(boolean cold, String result, long loads, long loadAttempts, long unloads,
                   String unloadReason, double loadMs, double contextMs, double grammarMs,
                   double promptMs, double generationMs, double totalMs, double queueMs,
                   double firstTokenMs, long ramBefore, long ramAfter,
                   double tokenizeMs, double prefillMs, double decodeMs, int cancellationReason) {
        String safeLine() {
            return "cold="+cold+" result="+result+" loads="+loads+" attempts="+loadAttempts+
                " unloads="+unloads+" unload_reason="+unloadReason+" load_ms="+loadMs+
                " context_ms="+contextMs+" grammar_ms="+grammarMs+" prompt_ms="+promptMs+
                " generation_ms="+generationMs+" total_ms="+totalMs+" queue_ms="+queueMs+
                " ttft_ms="+firstTokenMs+" ram_before="+ramBefore+" ram_after="+ramAfter+
                " tokenize_ms="+tokenizeMs+" prefill_ms="+prefillMs+" decode_ms="+decodeMs+" cancel_reason="+cancellationReason;
        }
    }
    record Output(String text, boolean stopped, Metrics metrics) {}
    final class Ticket {
        final CompletableFuture<Output> result = new CompletableFuture<>();
        final AtomicBoolean cancelled = new AtomicBoolean();
        final AtomicInteger cancellationReason = new AtomicInteger();
        final long submitted = System.nanoTime(), version;
        Ticket(long version) { this.version = version; }
        void cancel() { cancellationReason.compareAndSet(0,1);abort(this); }
        void timeout() { cancellationReason.compareAndSet(0,2);abort(this); }
    }
    private final Backend nativeApi;
    private final MemoryReader memory;
    private final Consumer<Metrics> observer;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(r -> daemon(r,"wiley-model"));
    private final ScheduledThreadPoolExecutor timer = new ScheduledThreadPoolExecutor(1,r -> daemon(r,"wiley-model-timer"));
    private final Object gate = new Object();
    private long handle, version, idleVersion, loads, attempts, unloads, finishedAt;
    private long idleMillis;
    private int pending;
    private Model loaded;
    private String desired = "", evict = "", lastUnload = "none";
    private Ticket active;
    private ScheduledFuture<?> idle;
    private boolean closed;
    private volatile Metrics latest;
    private final CompletableFuture<Void> terminated = new CompletableFuture<>();

    LocalModelSession(Backend nativeApi, MemoryReader memory, long idleMillis, Consumer<Metrics> observer) {
        this.nativeApi=nativeApi;this.memory=memory;this.idleMillis=idleMillis;this.observer=observer;
        timer.setRemoveOnCancelPolicy(true);timer.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
    }
    private static Thread daemon(Runnable r,String name) { Thread t=new Thread(r,name);t.setDaemon(true);return t; }
    private static double ms(long nanos) { return Math.round(nanos/10000.0)/100.0; }
    Metrics latest() { return latest; }
    CompletableFuture<Void> termination() { return terminated; }

    Ticket generate(Model model, String prompt, String grammar, Consumer<Boolean> state, Consumer<String> partial) {
        return generate(model,prompt,grammar,state,partial,()->{});
    }
    Ticket generate(Model model, String prompt, String grammar, Consumer<Boolean> state, Consumer<String> partial, Runnable firstOutput) {
        synchronized(gate) {
            Ticket ticket=new Ticket(version);
            if(closed || pending>=8) { ticket.result.completeExceptionally(new IOException(closed?"Локальный движок закрыт":"Очередь локальной модели занята"));return ticket; }
            if(!desired.equals(model.identity())) { desired=model.identity();version++;if(active!=null)abort(active); }
            ticket=new Ticket(version);Ticket admitted=ticket;
            cancelIdle();pending++;
            worker.execute(()->generate(admitted,model,prompt,grammar,state,partial,firstOutput));return admitted;
        }
    }
    private void check(Ticket t) {
        synchronized(gate) { if(closed || t.cancelled.get() || t.version!=version)throw new CancellationException(); }
    }
    private void abort(Ticket t) {
        synchronized(gate) {
            t.cancellationReason.compareAndSet(0,3);
            t.cancelled.set(true);
            if(active==t && handle!=0) {
                try { nativeApi.cancel(handle); }
                catch(RuntimeException|LinkageError failure) { evict="abort_error"; }
            }
        }
    }
    private void generate(Ticket t,Model model,String prompt,String grammar,Consumer<Boolean> state,Consumer<String> partial,Runnable firstOutput) {
        long started=System.nanoTime(), load=0, context=0, rule=0, preparation=0, generation=0, first=-1;
        long before=-1,after=-1;long[] nativeTimes={0,0,0};
        boolean cold=false, used=false, stopped=false, poisoned=false;
        String answer="";Throwable error=null;
        ScheduledFuture<?> deadline=null;
        try {
            check(t);synchronized(gate){active=t;}
            deadline=timer.schedule(t::timeout,95,TimeUnit.SECONDS);
            if(loaded!=null && !loaded.identity().equals(model.identity()))unload("model_changed");
            Memory info=memory.read();before=info.available();
            if(!info.sufficient()) { unload("memory_before");throw new IOException("Сейчас мало свободной памяти для разговорной модели. Закройте тяжёлые приложения и повторите."); }
            check(t);cold=loaded==null;state.accept(cold);
            if(cold) {
                long began=System.nanoTime();attempts++;
                used=true;
                long created=nativeApi.create();if(created==0)throw new IOException("Не удалось создать локальный движок");
                synchronized(gate){handle=created;if(t.cancelled.get())nativeApi.cancel(handle);}
                try{check(t);nativeApi.load(created,model.path());check(t);loaded=model;loads++;}
                finally{load=System.nanoTime()-began;}
            } else used=true;
            check(t);long began=System.nanoTime();
            try{nativeApi.prepare(handle);}finally{context=System.nanoTime()-began;}check(t);
            if(grammar!=null) { began=System.nanoTime();try{nativeApi.grammar(handle,grammar.getBytes(StandardCharsets.UTF_8));}finally{rule=System.nanoTime()-began;}check(t); }
            began=System.nanoTime();try{nativeApi.begin(handle,prompt.getBytes(StandardCharsets.UTF_8));}finally{preparation=System.nanoTime()-began;}check(t);
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();long updated=0;began=System.nanoTime();boolean ended=false;
            try {
                for(int i=0;i<256 && System.nanoTime()-began<TimeUnit.SECONDS.toNanos(90);i++) {
                    check(t);byte[] piece=nativeApi.next(handle);if(piece==null){ended=true;break;}bytes.write(piece);
                    if(first<0 && bytes.size()>0){first=System.nanoTime()-t.submitted;firstOutput.run();}
                    ByteBuffer input=ByteBuffer.wrap(bytes.toByteArray());CharBuffer output=CharBuffer.allocate(bytes.size());
                    StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPLACE).decode(input,output,false);output.flip();answer=output.toString();
                    if(System.nanoTime()-updated>TimeUnit.MILLISECONDS.toNanos(80)){updated=System.nanoTime();partial.accept(answer);}
                }
                check(t);if(!ended)answer+="\n\n[Достигнут лимит ответа для этой модели]";
            } finally { generation=System.nanoTime()-began; }
        } catch(Throwable failure) {
            stopped=t.cancelled.get() || failure instanceof CancellationException;
            if(!stopped || failure instanceof Error) { error=failure;poisoned=true; }
        } finally {
            if(deadline!=null)deadline.cancel(false);
            try {
                if(used && handle!=0) {
                    nativeTimes=nativeApi.timings(handle);nativeApi.finish(handle);
                    if(poisoned || loaded==null)unload(poisoned?"native_error":"cancelled_load");
                }
                Memory info=memory.read();after=info.available();
                if(!info.sufficient())unload("memory_after");
            } catch(Throwable cleanup) {
                error=cleanup;poisoned=true;
                try { unload("cleanup_error"); } catch(Throwable ignored) { /* handle was unpublished before release */ }
            }
            String eviction;
            synchronized(gate){stopped |= t.cancelled.get() || t.version!=version || closed;eviction=closed?"session_closed":evict;evict="";}
            try{if(!eviction.isEmpty())unload(eviction);after=memory.read().available();}
            catch(Throwable cleanup){if(error==null)error=cleanup;}
            synchronized(gate){if(active==t)active=null;pending--;finishedAt=System.nanoTime();scheduleIdle();}
            if(nativeTimes==null || nativeTimes.length!=3)nativeTimes=new long[]{0,0,0};
            String result=error!=null?"failed":stopped?"stopped":"completed";
            if(stopped)t.cancellationReason.compareAndSet(0,3);
            Metrics metrics=new Metrics(cold,result,loads,attempts,unloads,lastUnload,ms(load),ms(context),ms(rule),ms(preparation),ms(generation),ms(System.nanoTime()-t.submitted),ms(started-t.submitted),first<0?-1:ms(first),before,after,ms(nativeTimes[0]),ms(nativeTimes[1]),ms(nativeTimes[2]),t.cancellationReason.get());
            publish(metrics);
            if(error!=null)t.result.completeExceptionally(error);else t.result.complete(new Output(answer.trim(),stopped,metrics));
        }
    }
    private void publish(Metrics metrics) { latest=metrics;try{observer.accept(metrics);}catch(RuntimeException ignored){} }
    private void cancelIdle() { idleVersion++;if(idle!=null){idle.cancel(false);idle=null;} }
    private void scheduleIdle() {
        // Caller holds gate. Timer never frees native memory itself.
        if(closed || handle==0 || active!=null || pending>0)return;
        cancelIdle();long stamp=idleVersion;
        long remaining=Math.max(0,idleMillis-TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-finishedAt));
        idle=timer.schedule(()->{
            synchronized(gate){if(closed || stamp!=idleVersion)return;worker.execute(()->{
                synchronized(gate){if(stamp!=idleVersion || active!=null || pending>0)return;}
                unload("idle");
            });}
        },remaining,TimeUnit.MILLISECONDS);
    }
    void idleTimeout(long millis) {
        if(millis<1)throw new IllegalArgumentException();
        synchronized(gate){if(closed)return;if(idleMillis==millis)return;idleMillis=millis;cancelIdle();scheduleIdle();}
    }
    void release(String reason,boolean cancelRequests) {
        synchronized(gate) {
            if(closed)return;cancelIdle();evict=reason;
            if(cancelRequests){version++;if(active!=null)abort(active);}
            worker.execute(()->{unload(reason);synchronized(gate){if(evict.equals(reason))evict="";}});
        }
    }
    /** Installer validation and deletion share the same native owner and serial queue. */
    CompletableFuture<Void> maintenance(String reason,Runnable work) {
        CompletableFuture<Void> done=new CompletableFuture<>();
        synchronized(gate) {
            if(closed){done.completeExceptionally(new IOException("Движок закрыт"));return done;}
            cancelIdle();version++;if(active!=null)abort(active);
            worker.execute(()->{try{unload(reason);work.run();done.complete(null);}catch(Throwable e){done.completeExceptionally(e);}});
        }
        return done;
    }
    void probe(Model model,AtomicBoolean cancel) throws Exception {
        // Maintenance tasks may use a temporary candidate, never a second resident copy.
        CompletableFuture<Void> done=maintenance("install_probe",()->{
            Ticket probe; synchronized(gate){probe=new Ticket(version);active=probe;}
            ScheduledFuture<?> poll=timer.scheduleAtFixedRate(()->{if(cancel.get())probe.cancel();},0,25,TimeUnit.MILLISECONDS);
            try {
                check(probe);if(cancel.get())throw new CancellationException();
                if(!memory.read().sufficient())throw new IOException("Недостаточно памяти для проверки модели");
                attempts++;long candidate=nativeApi.create();if(candidate==0)throw new IOException("Не удалось создать движок");
                synchronized(gate){handle=candidate;if(probe.cancelled.get())nativeApi.cancel(handle);}
                check(probe);nativeApi.load(candidate,model.path());check(probe);loaded=model;loads++;
                if(cancel.get())throw new CancellationException();nativeApi.prepare(candidate);check(probe);
            }catch(IOException e){throw new CompletionException(e);}
            finally{poll.cancel(false);try{unload("install_probe");}finally{synchronized(gate){if(active==probe)active=null;}}}
        });
        done.get();
    }
    private void unload(String reason) {
        long old;
        synchronized(gate){old=handle;handle=0;loaded=null;}
        if(old==0)return;
        nativeApi.close(old);unloads++;lastUnload=reason;
        long available=-1;try{available=memory.read().available();}catch(IOException ignored){}
        publish(new Metrics(false,"unloaded",loads,attempts,unloads,reason,0,0,0,0,0,0,0,-1,-1,available,0,0,0,0));
    }
    @Override public void close() {
        synchronized(gate) {
            if(closed)return;closed=true;version++;cancelIdle();if(active!=null)abort(active);
            worker.execute(()->{try{unload("session_closed");terminated.complete(null);}catch(Throwable e){terminated.completeExceptionally(e);}finally{timer.shutdownNow();worker.shutdown();}});
        }
    }
}
