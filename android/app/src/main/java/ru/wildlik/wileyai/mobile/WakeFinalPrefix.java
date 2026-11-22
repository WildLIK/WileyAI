package ru.wildlik.wileyai.mobile;

import java.util.List;

/** Recovery for the specific extra words produced by the restricted Vosk grammar. */
final class WakeFinalPrefix {
    static final String PREFERENCE = "wake_final_prefix_experiment";
    private static final int RATE = 16000;
    private static final int GUARD = 1920;
    private static final List<List<String>> NAMES = List.of(
            List.of("окей", "вай", "ли"), List.of("окей", "уайли"), List.of("окей", "вайли"),
            List.of("вай", "ли"), List.of("уайли"), List.of("вайли"));

    record Word(String text, double start, double end, double confidence) {}
    record Match(String phrase, long end, long commandStart, double confidence) {}

    static Match recover(List<Word> words, long captured) {
        for (List<String> name : NAMES) {
            int length = name.size();
            if (words.size() <= length || words.size() > length + 2) continue;
            boolean matches = true;
            double confidence = 1;
            for (int i = 0; i < length; i++) {
                Word w = words.get(i);
                if (!name.get(i).equals(w.text()) || !Double.isFinite(w.confidence()) ||
                        w.confidence() < WakePhrase.MIN_CONFIDENCE || w.confidence() > 1) {
                    matches = false;
                    break;
                }
                confidence = Math.min(confidence, w.confidence());
            }
            if (!matches) continue;
            String suffix = words.get(length).text();
            boolean allowed = words.size() == length + 1
                    ? "ли".equals(suffix) || "поговорим".equals(suffix)
                    : "ли".equals(suffix) && "ли".equals(words.get(length + 1).text());
            if (!allowed) return null;
            double first = words.get(0).start();
            double last = words.get(length - 1).end();
            double suffixStart = words.get(length).start();
            if (!Double.isFinite(first) || !Double.isFinite(last) || !Double.isFinite(suffixStart)) return null;
            long start = Math.round(first * RATE);
            long end = Math.round(last * RATE);
            long next = Math.round(suffixStart * RATE);
            if (start < 0 || end <= start || end > captured || end - start < 2400 ||
                    end - start > 24000 || captured - end > 2L * RATE ||
                    next < end - 160 || next > Math.min(captured, end + 9600)) return null;
            return new Match(String.join(" ", name), end, Math.max(0, end - GUARD), confidence);
        }
        return null;
    }

    private WakeFinalPrefix() {}
}
