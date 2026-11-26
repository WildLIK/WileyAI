package ru.wildlik.wileyai.mobile;

import java.util.Arrays;

/** Bounded, in-memory PCM pre-roll; callers never receive the mutable backing array. */
final class PcmRingBuffer {
    private final short[] samples;
    private int next, size;

    PcmRingBuffer(int capacity) {
        if (capacity <= 0) throw new IllegalArgumentException("capacity must be positive");
        samples = new short[capacity];
    }

    synchronized void append(short[] source, int offset, int length) {
        if (source == null || offset < 0 || length < 0 || offset > source.length - length)
            throw new IllegalArgumentException("invalid PCM range");
        // Only the most recent capacity samples can survive the write.
        if (length > samples.length) { offset += length - samples.length; length = samples.length; }
        int first = Math.min(length, samples.length - next);
        System.arraycopy(source, offset, samples, next, first);
        System.arraycopy(source, offset + first, samples, 0, length - first);
        next = (next + length) % samples.length;
        size = Math.min(samples.length, size + length);
    }

    synchronized short[] snapshot() {
        return snapshotTail(size);
    }

    synchronized int size() { return size; }

    synchronized short[] snapshotTail(int count) {
        if (count < 0 || count > size) throw new IllegalArgumentException("PCM tail outside retained audio");
        short[] out = new short[count];
        int start = (next - count + samples.length) % samples.length;
        int first = Math.min(count, samples.length - start);
        System.arraycopy(samples, start, out, 0, first);
        System.arraycopy(samples, 0, out, first, count - first);
        return out;
    }

    synchronized short[] drain() {
        short[] out = snapshot();
        clear();
        return out;
    }

    synchronized void clear() {
        Arrays.fill(samples, (short) 0);
        next = size = 0;
    }
}
