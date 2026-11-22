package ru.wildlik.wileyai.mobile;

import java.util.Arrays;
import java.util.concurrent.locks.ReentrantLock;

/** A bounded observer queue. Only the worker can wait; the audio producer never waits. */
final class H2Windows {
    static final int RATE = 16000, HOP = 1280, CAPACITY = 3;
    static final class Slot {
        final short[] pcm = new short[RATE];
        long capture, end;
    }
    private final ReentrantLock producer = new ReentrantLock();
    private final Slot[] slots = {new Slot(), new Slot(), new Slot()};
    private final short[] history = new short[RATE];
    private volatile long written, read;
    volatile long dropped, warmup;
    private volatile boolean closed;
    private long capture = -1, cursor, validAfter;
    private int head;

    void feed(long id, long first, short[] data, int count) {
        if (!producer.tryLock()) return;
        try {
            if (closed) return;
            if (capture != id || cursor != first) {
                Arrays.fill(history, (short)0);
                head = 0;
                capture = id;
                cursor = first;
                validAfter = first == 0 ? 0 : first + RATE;
            }
            int offset = 0;
            while (offset < count) {
                int n = Math.min(count-offset, Math.min(RATE-head, HOP-(int)(cursor%HOP)));
                System.arraycopy(data,offset,history,head,n);
                head = (head+n)%RATE;
                cursor += n;
                offset += n;
                if (cursor%HOP != 0) continue;
                if (cursor < validAfter) { warmup++; continue; }
                if (written-read >= CAPACITY) { dropped++; continue; }
                Slot slot = slots[(int)(written%CAPACITY)];
                System.arraycopy(history,head,slot.pcm,0,RATE-head);
                System.arraycopy(history,0,slot.pcm,RATE-head,head);
                slot.capture = id;
                slot.end = cursor;
                written++;
            }
        } finally { producer.unlock(); }
    }
    void end(long id) {
        if (!producer.tryLock()) return;
        try {
            if (capture == id) { Arrays.fill(history,(short)0); capture = -1; }
        } finally { producer.unlock(); }
    }
    Slot next() { return read == written ? null : slots[(int)(read%CAPACITY)]; }
    void release(Slot slot) { Arrays.fill(slot.pcm,(short)0); read++; }
    long close() {
        producer.lock();
        try {
            closed = true;
            Arrays.fill(history,(short)0);
            for (Slot slot : slots) Arrays.fill(slot.pcm,(short)0);
            return written-read;
        } finally { producer.unlock(); }
    }
    static final class Decision {
        long capture = -1, previous, rearm;
        int run;
        boolean update(long id, long end, float score) {
            if (capture != id) { capture = id; run = 0; rearm = 0; }
            if (previous + HOP != end) run = 0;
            previous = end;
            run = score >= .15f ? run+1 : 0;
            if (run != 2 || end < rearm) return false;
            rearm = end + 12800;
            return true;
        }
    }
}
