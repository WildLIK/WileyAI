package ru.wildlik.wileyai.mobile;

import java.util.ArrayList;
import java.util.List;

public final class WakeComparisonPcmProbe {
    public static void main(String[] args) {
        List<Long> ends = new ArrayList<>();
        WakeComparisonPcm pcm = new WakeComparisonPcm();
        short[] block = new short[2048];
        for (int i = 0; i < block.length; i++) block[i] = (short) (i + 50);
        check(pcm.append(1, 30, block, 347, (end, x) -> {}).reset());
        pcm.append(1, 377, block, 933, (end, x) -> {
            ends.add(end);
            check(x[346] == 396 && x[347] == 50 && x[1279] == 982);
        });
        check(ends.equals(List.of(1310L)));
        var gap = pcm.append(1, 1350, block, 1280, (end, x) -> ends.add(end));
        check(gap.reset() && gap.lost() == 40 && ends.equals(List.of(1310L, 2630L)));
        check(pcm.append(2, 0, block, 1, (end, x) -> {}).reset());

        var rule = new WakeComparisonPcm.Decision();
        check(!rule.update(1280, .99f));
        check(rule.update(2560, .99f));
        for (int i = 3; i < 12; i++) check(!rule.update(i * 1280L, 1f));
        check(!rule.update(15360, .8f));
        check(!rule.update(16640, 1f));
        check(rule.update(17920, 1f));
        rule.reset();
        check(!rule.update(1280, 1f) && rule.update(2560, 1f));

        rule.reset();
        check(!rule.update(1280, 1f) && rule.update(2560, 1f));
        check(!rule.update(3840, .8f));
        check(!rule.update(5120, 1f));
        check(!rule.update(6400, 1f)); // During refractory interval.
        check(!rule.update(15360, 1f)); // Same streak cannot fire again after cooldown.
    }

    private static void check(boolean condition) {
        if (!condition) throw new AssertionError();
    }
}
