package ru.wildlik.wileyai.mobile;

import java.util.List;

/** Context-matching rules against the C9 projection: the owner's reported cases and their negatives. */
public final class ScreenContextMatcherProbe {
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    static List<String> labels = List.of("ЗВЁЗДНАЯ КАРТА", "ЛЕСНАЯ ТРОПА", "Поиск", "Настройки");
    public static void main(String[] args) {
        // The owner's case: noisy STT output must find the label without any hard-coded dictionary.
        List<ScreenContextMatcher.Candidate> found = ScreenContextMatcher.match("найти с вест моя карта", labels);
        check(!found.isEmpty() && found.get(0).label().equals("звездная карта") && found.get(0).score() >= ScreenContextMatcher.STRONG);
        check(!ScreenContextMatcher.ambiguous(found));
        // Cleaner forms match too.
        check(ScreenContextMatcher.match("найти звёздную карту", labels).get(0).label().equals("звездная карта"));
        check(ScreenContextMatcher.match("найди кнопку звёздная карта", labels).get(0).label().equals("звездная карта"));
        check(ScreenContextMatcher.match("найти лесная тропа", labels).get(0).label().equals("лесная тропа"));
        check(ScreenContextMatcher.match("Где кнопка поиска?", labels).get(0).label().equals("поиск"));
        // The other label must not win.
        check(ScreenContextMatcher.match("найти лесная тропа", labels).stream().noneMatch(c -> c.label().equals("звездная карта")));
        // Ambiguity asks for clarification instead of guessing; a too-short query yields no guess at all.
        List<ScreenContextMatcher.Candidate> similar = ScreenContextMatcher.match("найти карту", List.of("КАРТА ГОРОДА", "КАРТА МИРА", "Настройки"));
        check(similar.isEmpty()); // short noisy query: no confident candidate, falls back to the model path
        check(ScreenContextMatcher.ambiguous(List.of(new ScreenContextMatcher.Candidate("карта города", 0.70), new ScreenContextMatcher.Candidate("карта мира", 0.66))));
        check(!ScreenContextMatcher.ambiguous(List.of(new ScreenContextMatcher.Candidate("карта города", 0.90), new ScreenContextMatcher.Candidate("карта мира", 0.60))));
        // A negated phrase is never rewritten, even when the label matches the rest of the words.
        check(ScreenContextMatcher.match("не нажимай звездную карту", labels).isEmpty());
        check(ScreenContextMatcher.match("не открывай карту", List.of("КАРТА ГОРОДА", "КАРТА МИРА")).isEmpty());
        // Music and software queries never turn into screen labels (§8.8).
        check(ScreenContextMatcher.match("продолжи музыку", labels).isEmpty());
        check(ScreenContextMatcher.match("открой телеграм", labels).isEmpty());
        check(ScreenContextMatcher.match("включи noize mc", labels).isEmpty());
        // Negations and non-screen intents never produce candidates.
        check(ScreenContextMatcher.match("как работает навигация", labels).isEmpty());
        check(ScreenContextMatcher.match("что сейчас открыто", labels).isEmpty());
        check(ScreenContextMatcher.match("", labels).isEmpty());
        check(ScreenContextMatcher.match("найти что-нибудь", List.of()).isEmpty());
        // The correction record stays in memory only and carries all four required fields.
        ScreenContextMatcher.record(new ScreenContextMatcher.Correction("найти с вест моя карта", ScreenContextMatcher.query("найти с вест моя карта"), "фонетический скелет согласных", List.of("звездная карта"), "звездная карта", "screen_find"));
        ScreenContextMatcher.Correction last = ScreenContextMatcher.last();
        check(last != null && last.original().equals("найти с вест моя карта") && last.chosen().equals("звездная карта") && last.intent().equals("screen_find") && !last.basis().isEmpty());
        ScreenContextMatcher.clear();
        check(ScreenContextMatcher.last() == null);
        System.out.println("Screen context matcher checks passed");
    }
}
