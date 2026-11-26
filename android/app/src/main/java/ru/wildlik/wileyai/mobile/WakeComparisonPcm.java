package ru.wildlik.wileyai.mobile;

/** Coordinates are end-exclusive samples within the existing capture. */
final class WakeComparisonPcm {
    static final int RATE = 16000, BLOCK = 1280;
    record Change(boolean reset, long lost, int abandoned) {}
    interface Scorer { void score(long end, short[] samples); }

    private final short[] window = new short[BLOCK];
    private long capture = -1, next;
    private int buffered;

    Change append(long epoch, long start, short[] pcm, int count, Scorer scorer) {
        boolean reset = capture != epoch || next != start;
        long lost = capture == epoch ? Math.max(0, start - next) : 0;
        int abandoned = reset ? buffered : 0;
        if (reset) { capture = epoch; buffered = 0; }
        for (int offset = 0; offset < count;) {
            int size = Math.min(count - offset, BLOCK - buffered);
            System.arraycopy(pcm, offset, window, buffered, size);
            offset += size;
            buffered += size;
            if (buffered == BLOCK) {
                scorer.score(start + offset, window);
                buffered = 0;
            }
        }
        next = start + count;
        return new Change(reset, lost, abandoned);
    }

    boolean discontinuity(long epoch, long start) { return capture != epoch || next != start; }
    int pending() { return buffered; }

    static final class Decision {
        static final float THRESHOLD = .99f;
        static final int REARM = 800 * RATE / 1000;
        private long previous;
        private int streak;

        Decision() { reset(); }
        void reset() { previous = -REARM; streak = 0; }

        boolean update(long end, float score) {
            streak = score >= THRESHOLD ? Math.min(3, streak + 1) : 0;
            if (streak != 2 || end - previous < REARM) return false;
            previous = end;
            return true;
        }
    }
}
