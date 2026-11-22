package ru.wildlik.wileyai.mobile;
import java.util.Locale;
final class NotePresentation {
 static String title(String text) { String first=text.strip().split("\\R",2)[0].strip(); return first.isEmpty()?"Без названия":first; }
 static boolean matches(String text,String query) { return text.toLowerCase(Locale.ROOT).contains(query.strip().toLowerCase(Locale.ROOT)); }
}
