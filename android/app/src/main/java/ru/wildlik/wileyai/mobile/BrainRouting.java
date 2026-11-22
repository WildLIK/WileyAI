package ru.wildlik.wileyai.mobile;

import java.util.Locale;
import java.util.regex.Pattern;

/** Only stand-alone, low-complexity questions qualify for the local fast model. */
final class BrainRouting {
    private static final Pattern SIMPLE = Pattern.compile(
        "(?:что такое [\\p{L}\\d -]+|переведи на (?:английский|русский) [\\p{L}\\d -]+|"
            + "сколько будет (?:[\\d +*/×÷−-]|ноль|один|два|три|четыре|пять|шесть|семь|восемь|девять|десять|плюс|минус|умножить|делить|на)+)[?.!]?");
    private static final Pattern COMPLEX = Pattern.compile(
        "(?<![\\p{L}\\p{N}_])(?:и|или|затем|сравни|объясни|почему|как|докажи|подробно|распиши|план|который|которого)(?![\\p{L}\\p{N}_])");

    static boolean simple(String request) {
        String text = request.trim().toLowerCase(Locale.ROOT).replaceAll("\\s+", " ");
        return text.length() <= 100 && text.split(" ").length <= 12
            && SIMPLE.matcher(text).matches() && !COMPLEX.matcher(text).find();
    }

    private BrainRouting() {}
}
