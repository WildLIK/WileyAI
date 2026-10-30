package ru.wildlik.wileyai.mobile;

import java.util.Locale;

/** Explicit complete wake phrases; no substring, negation or fuzzy matching of decoder text. */
public final class WakePhrase {
    public static final String DEFAULT = "окей вайли";
    public static final String[] PRESETS = {DEFAULT, "привет помощник", "слушай помощник"};
    public static boolean valid(String phrase) { return java.util.Arrays.asList(PRESETS).contains(phrase); }
    public static String label(String phrase) { return DEFAULT.equals(phrase) ? "Окей, Вайли" : "слушай помощник".equals(phrase) ? "Слушай, помощник" : "Привет, помощник"; }
    public static String[] decoderPhrases(String phrase) { return DEFAULT.equals(phrase) ? new String[]{"окей уайли", "окей вай ли"} : new String[]{phrase}; }
    public static boolean conversation(String phrase,String heard,double confidence) {
        if(heard==null)return false;
        String normalized=heard.toLowerCase(Locale.ROOT).replaceAll("[,.!?]"," ").trim().replaceAll("\\s+"," ");
        String suffix=" давай поговорим";
        return normalized.endsWith(suffix) && matches(phrase,normalized.substring(0,normalized.length()-suffix.length()),confidence);
    }
    public static boolean matches(String phrase, String heard, double minimumConfidence) {
        if (!valid(phrase) || heard == null || !Double.isFinite(minimumConfidence) || minimumConfidence < .75 || minimumConfidence > 1) return false;
        String normalized = heard.toLowerCase(Locale.ROOT).replace('ё', 'е').replaceAll("[,.!?]", " ").trim().replaceAll("\\s+", " ");
        if (phrase.equals(normalized)) return true;
        for (String decoded : decoderPhrases(phrase)) if (decoded.equals(normalized)) return true;
        return false;
    }
    private WakePhrase() {}
}
