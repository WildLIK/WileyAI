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
        short[] out = new short[size];
        int start = (next - size + samples.length) % samples.length;
        int first = Math.min(size, samples.length - start);
        System.arraycopy(samples, start, out, 0, first);
        System.arraycopy(samples, 0, out, first, size - first);
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
