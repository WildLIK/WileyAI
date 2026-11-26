package ru.wildlik.wileyai.mobile;

import java.util.ArrayDeque;
import java.util.Arrays;

/** One-producer, one-consumer, bounded in-memory PCM handoff. No recording is persisted. */
final class PcmHandoff {
    private final PcmRingBuffer history;
    private final int capacity;
    private final ArrayDeque<short[]> queue = new ArrayDeque<>();
    private long written;
    private int queued, offset;
    private boolean active, closed, sealed, overflow;
    private long boundary=-1,accepted,delivered,overflowSamples,discarded;
    private int peak;
    record Stats(long boundarySample,long acceptedSamples,long deliveredSamples,long overflowSamples,long discardedSamples,int queuedSamples,int peakQueuedSamples) {}
    synchronized Stats stats(){return new Stats(boundary,accepted,delivered,overflowSamples,discarded,queued,peak);}

    PcmHandoff(int historySamples, int queuedSamples) {
        if (queuedSamples <= 0) throw new IllegalArgumentException("invalid queue capacity");
        history = new PcmRingBuffer(historySamples);
        capacity = queuedSamples;
    }

    synchronized long position() { return written; }
    synchronized boolean isActive() { return active && !closed && !sealed && !overflow; }
    synchronized int bufferedSamples() { return queued; }

    synchronized void append(short[] samples, int length) {
        if (samples == null || length < 0 || length > samples.length) throw new IllegalArgumentException("invalid PCM");
        if (closed || sealed || overflow) throw new IllegalStateException("handoff closed");
        if (!active) history.append(samples, 0, length);
        else enqueue(Arrays.copyOf(samples, length));
        written += length;
        notifyAll();
    }

    /** Boundary is an absolute sample position in the current capture, inclusive. */
    synchronized void activate(long commandStart) {
        if (active || closed || sealed || overflow) throw new IllegalStateException("handoff unavailable");
        long first = written - history.size();
        if (commandStart < first || commandStart > written) throw new IllegalArgumentException("boundary outside retained audio");
        short[] retained = history.snapshotTail((int)(written - commandStart));
        active = true;
        boundary=commandStart;
        enqueue(retained);
        history.clear();
        notifyAll();
    }

    private void enqueue(short[] pcm) {
        if (pcm.length > capacity - queued) {
            overflowSamples+=pcm.length;
            Arrays.fill(pcm, (short) 0);
            overflow = true;
            notifyAll();
            throw new IllegalStateException("PCM queue overflow");
        }
        if (pcm.length != 0) { queue.add(pcm); queued += pcm.length;accepted+=pcm.length;peak=Math.max(peak,queued); }
    }

    /** Returns 0 on timeout, -1 on end; overflow is an error, never silent sample loss. */
    synchronized int read(short[] target, int timeoutMs) throws InterruptedException {
        if (target == null || target.length == 0 || timeoutMs < 0) throw new IllegalArgumentException("invalid read");
        long deadline = System.nanoTime() + timeoutMs * 1_000_000L;
        while (queue.isEmpty() && !closed && !sealed && !overflow) {
            long remaining = deadline - System.nanoTime();
            if (remaining <= 0) return 0;
            wait(Math.max(1, remaining / 1_000_000L));
        }
        if (overflow) throw new IllegalStateException("PCM queue overflow");
        if (queue.isEmpty()) return -1;
        short[] first = queue.peek();
        int n = Math.min(target.length, first.length - offset);
        System.arraycopy(first, offset, target, 0, n);
        Arrays.fill(first, offset, offset + n, (short)0);
        offset += n; queued -= n;
        delivered+=n;
        if (offset == first.length) { queue.remove(); offset = 0; }
        return n;
    }

    /** Stop accepting PCM while preserving already accepted samples for a bounded drain. */
    synchronized void seal() { sealed = true; notifyAll(); }

    synchronized void close() {
        closed = true;
        discarded+=queued;
        history.clear();
        for (short[] item : queue) Arrays.fill(item, (short)0);
        queue.clear(); queued = offset = 0;
        notifyAll();
    }
}
