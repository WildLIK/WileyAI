package ru.wildlik.wileyai.mobile;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Conservative phonetic alignment between recognized speech and the already-permitted C9 projection.
 * Never starts an observation by itself, never rewrites a phrase into the closest label, never acts:
 * it only proposes candidate labels for an explicitly authorized screen request.
 */
final class ScreenContextMatcher {
    static final double STRONG = 0.62, AMBIGUOUS_GAP = 0.08;
    record Candidate(String label, double score) {}
    /** Original text, merged suggestion, matching basis and the intent chosen for them, kept out of persistent logs. */
    record Correction(String original, String normalized, String basis, List<String> labels, String chosen, String intent) {}
    private static volatile Correction last;
    static Correction last() { return last; }
    static void record(Correction correction) { last = correction; }
    static void clear() { last = null; }
    private static String normalize(String text) {
        if (text == null) return "";
        StringBuilder out = new StringBuilder();
        for (char raw : text.toLowerCase(Locale.ROOT).replace('ё', 'е').toCharArray()) {
            if (raw >= 'а' && raw <= 'я' || raw == ' ' || raw >= 'a' && raw <= 'z') out.append(raw);
        }
        return out.toString().replaceAll("\\s+", " ").trim();
    }
    private static boolean stopWord(String word) {
        // Exact command-structure words only: a trailing .* would turn single-letter prepositions
        // into prefix patterns and erase real content like «карта».
        return word.matches("(?s)(?:найди|найдите|найти|где|покажи|есть|ли|кнопк(?:а|у|и|е|ой|ную)?|поле|строк(?:а|у|и|е|ой|у)?|экран(?:а|е|у|е)?|здесь|тут|отсюда|мне|ты|видишь|что|сейчас|открыто|открыта|открыт|передо|пожалуйста|уайли|вайли|на|в|и|с|к|по|за|это|эту|ту|тот|свой|свою|которая|который|нажми|нажать|нажимай|нажим|хочу|давай|продолжи|включи|выключи|для|как)");
    }
    static List<Candidate> match(String request, List<String> labels) {
        List<Candidate> out = new ArrayList<>();
        String query = normalize(request);
        if (query.isEmpty() || labels == null || labels.isEmpty()) return out;
        for (String word : query.split(" ")) {
            // A negated or cancelled phrase is never rewritten into a screen label.
            if (word.equals("не") || word.equals("нельзя") || word.equals("стоп") || word.startsWith("отмен")) return out;
        }
        StringBuilder words = new StringBuilder();
        for (String word : query.split(" ")) if (!word.isEmpty() && !stopWord(word)) words.append(word).append(' ');
        String merged = words.toString().trim();
        if (merged.isEmpty()) return out;
        String querySkeleton = skeleton(merged.replace(" ", ""));
        for (String label : labels) {
            String clean = normalize(label);
            if (clean.isEmpty() || clean.length() > 64) continue;
            double score = similarity(querySkeleton, skeleton(clean.replace(" ", "")));
            out.add(new Candidate(clean, Math.round(score * 1000.0) / 1000.0));
        }
        out.sort((a, b) -> Double.compare(b.score(), a.score()));
        List<Candidate> strong = new ArrayList<>();
        for (Candidate candidate : out) if (candidate.score() >= STRONG) strong.add(candidate); else break;
        return strong;
    }
    /** True when the second candidate is close enough to the best one that a clarification is required. */
    static boolean ambiguous(List<Candidate> candidates) {
        return candidates.size() >= 2 && candidates.get(0).score() - candidates.get(1).score() < AMBIGUOUS_GAP;
    }
    static String query(String request) {
        String query = normalize(request);
        StringBuilder words = new StringBuilder();
        for (String word : query.split(" ")) if (!word.isEmpty() && !stopWord(word)) words.append(word).append(' ');
        return words.toString().trim();
    }
    /** Consonant skeleton: vowels and soft signs drop out, so "звездная" and "с вестная-like noise" stay comparable. */
    private static String skeleton(String word) {
        StringBuilder out = new StringBuilder();
        for (char c : word.toCharArray()) {
            if (c == 'а' || c == 'е' || c == 'о' || c == 'у' || c == 'ы' || c == 'э' || c == 'ю' || c == 'я' || c == 'и' || c == 'ь' || c == 'ъ') continue;
            out.append(c);
        }
        return out.toString();
    }
    private static double substitute(char a, char b) {
        if (a == b) return 0;
        String pair = a < b ? "" + a + b : "" + b + a;
        return switch (pair) {
            case "зс", "дт", "бп", "гк", "фв", "жз" -> 0.4;
            case "жш", "шс", "щс", "сц", "тц", "чц" -> 0.5;
            case "щш" -> 0.3;
            case "лр", "мн" -> 0.7;
            case "кх" -> 0.6;
            default -> 1.0;
        };
    }
    private static double similarity(String a, String b) {
        if (a.isEmpty() || b.isEmpty()) return 0;
        int n = a.length(), m = b.length();
        double[] previous = new double[m + 1], current = new double[m + 1];
        for (int j = 0; j <= m; j++) previous[j] = j;
        for (int i = 1; i <= n; i++) {
            current[0] = i;
            for (int j = 1; j <= m; j++) {
                double sub = previous[j - 1] + substitute(a.charAt(i - 1), b.charAt(j - 1));
                double delete = previous[j] + 1, insert = current[j - 1] + 1;
                current[j] = Math.min(sub, Math.min(delete, insert));
            }
            double[] swap = previous; previous = current; current = swap;
        }
        double distance = previous[m];
        return Math.max(0, 1 - distance / Math.max(n, m));
    }
    private ScreenContextMatcher() {}
}
