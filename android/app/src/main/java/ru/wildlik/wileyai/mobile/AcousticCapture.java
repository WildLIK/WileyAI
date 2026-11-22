package ru.wildlik.wileyai.mobile;

/** Positions refer to the PCM seen by one capture epoch, before decoder or VAD processing. */
final class AcousticCapture {
    static final int RATE = 16000, BEFORE = 8 * RATE, AFTER = 3 * RATE;
    private final PcmRingBuffer ring = new PcmRingBuffer(BEFORE);
    private long position;

    void feed(short[] block, int count) { ring.append(block, 0, count); position += count; }
    long position() { return position; }
    void reset() { ring.clear(); position = 0; }
    Window mark(boolean tail) { return new Window(position, ring.snapshot(), tail); }

    static final class Window {
        final long start, event;
        final short[] samples;
        int length;
        Window(long position, short[] head, boolean tail) {
            event = position;
            start = position - head.length;
            samples = tail ? java.util.Arrays.copyOf(head, head.length + AFTER) : head;
            length = head.length;
        }
        boolean add(short[] block, int count) {
            int copy = Math.min(count, samples.length - length);
            System.arraycopy(block, 0, samples, length, copy);
            length += copy;
            return length == samples.length;
        }
    }
}
