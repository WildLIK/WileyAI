package ru.wildlik.wileyai.mobile;

import java.util.Locale;

/** Explicit complete wake phrases; no substring, negation or fuzzy matching of decoder text. */
public final class WakePhrase {
    public static final String DEFAULT = "окей вайли";
    public static final String SHORT = "вайли";
    static final double MIN_CONFIDENCE = .75;
    public static final String[] PRESETS = {SHORT, DEFAULT, "привет помощник", "слушай помощник"};
    public static boolean valid(String phrase) { return java.util.Arrays.asList(PRESETS).contains(phrase); }
    public static String label(String phrase) { return SHORT.equals(phrase) ? "Вайли" : DEFAULT.equals(phrase) ? "Окей, Вайли" : "слушай помощник".equals(phrase) ? "Слушай, помощник" : "Привет, помощник"; }
    public static String[] decoderPhrases(String phrase) {
        if(SHORT.equals(phrase))return new String[]{"уайли", "вай ли", "окей уайли", "окей вай ли"};
        if(DEFAULT.equals(phrase))return new String[]{"окей уайли", "окей вай ли"};
        return new String[]{phrase};
    }
    public static boolean conversation(String phrase,String heard,double confidence) {
        if(heard==null)return false;
        String normalized=heard.toLowerCase(Locale.ROOT).replaceAll("[,.!?]"," ").trim().replaceAll("\\s+"," ");
        String suffix=" давай поговорим";
        return normalized.endsWith(suffix) && matches(phrase,normalized.substring(0,normalized.length()-suffix.length()),confidence);
    }
    public static boolean matches(String phrase, String heard, double minimumConfidence) {
        if (!valid(phrase) || heard == null || !Double.isFinite(minimumConfidence) || minimumConfidence < MIN_CONFIDENCE || minimumConfidence > 1) return false;
        String normalized = heard.toLowerCase(Locale.ROOT).replace('ё', 'е').replaceAll("[,.!?]", " ").trim().replaceAll("\\s+", " ");
        if (phrase.equals(normalized)) return true;
        if (SHORT.equals(phrase) && DEFAULT.equals(normalized)) return true;
        for (String decoded : decoderPhrases(phrase)) if (decoded.equals(normalized)) return true;
        return false;
    }
    /** Export only an allowlisted variant code, including presets for alternate names. */
    static int variant(String heard,boolean dialogue){
        String word=heard.toLowerCase(Locale.ROOT).replaceAll("[,.!?]"," ").trim().replaceAll("\\s+"," ");
        if(dialogue)word=word.substring(0,word.length()-" давай поговорим".length());
        return switch(word){
            case "вайли" -> 1; case "уайли" -> 2; case "вай ли" -> 3;
            case "окей уайли" -> 4; case "окей вай ли" -> 5; case "окей вайли" -> 6;
            case "привет помощник" -> 7; case "слушай помощник" -> 8; default -> 0;
        };
    }
    /** Remove only a complete wake phrase at the beginning of a captured utterance. */
    static String removeLeadingWake(String text, String phrase) {
        if (text == null || !valid(phrase)) return text == null ? "" : text;
        java.util.List<String> candidates = new java.util.ArrayList<>();
        candidates.add(phrase); candidates.addAll(java.util.Arrays.asList(decoderPhrases(phrase)));
        if (SHORT.equals(phrase)) { candidates.add(DEFAULT); candidates.add("окей уайли"); candidates.add("окей вай ли"); }
        candidates.sort((a,b)->Integer.compare(b.length(),a.length()));
        for (String candidate : candidates) {
            String[] tokens=candidate.split(" ");StringBuilder prefix=new StringBuilder();for(String token:tokens){if(prefix.length()>0)prefix.append("[\\s,]+");prefix.append(java.util.regex.Pattern.quote(token));}
            java.util.regex.Matcher m=java.util.regex.Pattern.compile("(?iu)^\\s*"+prefix+"(?=$|[\\s,.:;!?—-])\\s*[,.:;!?—-]*\\s*").matcher(text);
            if(m.find())return text.substring(m.end()).trim();
        }
        return text;
    }
    /** Resolve a known ASR homophone only after a confirmed wake and a recognized complete command. */
    static String removeConfusableWake(String text,String phrase,java.util.function.Predicate<String> recognizedCommand) {
        if(text==null || !(SHORT.equals(phrase)||DEFAULT.equals(phrase)) || recognizedCommand==null)return text;
        if (text.trim().matches("(?iu)вали[,.!?—-]*")) return "";
        java.util.regex.Matcher m=java.util.regex.Pattern.compile("(?iu)^\\s*вали[,.:;!?—-]*\\s+(.+)$").matcher(text);
        if(!m.matches())return text;
        String remainder=m.group(1).trim();
        return recognizedCommand.test(remainder)?remainder:text;
    }
    private WakePhrase() {}
}
