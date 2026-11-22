package ru.wildlik.wileyai.mobile;

import java.util.Locale;
import java.util.regex.Pattern;

/** Matches only direct, complete memory requests. */
final class MemoryCommand {
    enum Kind { SAVE, FORGET, LIST }
    record Request(Kind kind,String text) {}
    private static final Pattern SAVE=Pattern.compile("(?iu)^запомни\\s*,?\\s+что\\s+(.+?)[.!?]*$");
    private static final Pattern FORGET=Pattern.compile("(?iu)^забудь\\s*,?\\s+что\\s+(.+?)[.!?]*$");
    static Request parse(String input){
        if(input==null||input.length()>450||input.contains("\n")||input.contains("«")||input.contains("\""))return null;
        String text=input.trim();
        if(text.toLowerCase(Locale.ROOT).replace('ё','е').matches("(?s).*(?:передумал|передумала|хотя нет|не надо|не сохраняй).*"))return null;
        if(text.toLowerCase(Locale.ROOT).replace('ё','е').matches("что ты обо мне помнишь[?! .]*"))return new Request(Kind.LIST,"");
        var save=SAVE.matcher(text);
        if(save.matches()&&save.group(1).matches("(?s).*\\p{L}.*"))return new Request(Kind.SAVE,save.group(1).trim());
        var forget=FORGET.matcher(text);
        if(forget.matches()&&forget.group(1).matches("(?s).*\\p{L}.*"))return new Request(Kind.FORGET,forget.group(1).trim());
        return null;
    }
    static boolean matches(String stored,String query){
        return stored.toLowerCase(Locale.ROOT).replace('ё','е').contains(query.toLowerCase(Locale.ROOT).replace('ё','е'));
    }
    static boolean ambiguousMutation(String input){
        return input!=null&&input.toLowerCase(Locale.ROOT).replace('ё','е').matches("(?s).*(?:запомни|забудь).*");
    }
    static int selection(String input){
        String value=input.toLowerCase(Locale.ROOT).replace('ё','е').replaceAll("[.!?,]", " ").trim().replaceAll("\\s+"," ");
        String[] names={"(?:перв(?:ый|ое|ую)|один|одна|1)","(?:втор(?:ой|ое|ую)|два|две|2)","(?:трет(?:ий|ье|ью)|три|3)","(?:четверт(?:ый|ое|ую)|четыре|4)","(?:пят(?:ый|ое|ую)|пять|5)"};
        for(int i=0;i<names.length;i++)if(value.matches("(?:номер |вариант )?"+names[i]+"(?: вариант)?"))return i;
        return -1;
    }
    private MemoryCommand(){}
}
