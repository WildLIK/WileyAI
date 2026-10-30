package ru.wildlik.wileyai.mobile;

import java.util.Locale;

/** A bounded alias dictionary, not fuzzy matching or model-mediated app selection. */
public final class SpokenNames {
    private SpokenNames() {}
    private static final String[][] NAMES = {
        {"deepseek", "дипсик", "дип сик", "дипсик аи", "тип сик", "типсик", "дип сек"},
        {"qwen", "квен", "квэн", "кьювен", "кувен"}, {"chatgpt", "чат жпт", "чат джипити", "чат джи пи ти", "чат гпт"},
        {"tiktok", "тик ток", "тикток"}, {"instagram", "инстаграм", "инстаграмм"}, {"discord", "дискорд"},
        {"spotify", "спотифай"}, {"vk", "вк", "вконтакте", "в контакте"}, {"vk music", "вк музыка", "вк музыку"},
        {"gigachat", "гигачат", "гига чат"}, {"perplexity", "перплексити"}, {"gemini", "джемини", "гемини"},
        {"claude", "клод", "клауд"}, {"grok", "грок"}, {"copilot", "копилот", "ко пилот"},
        {"venice ai", "венис", "венеция", "венис аи"}, {"openchat", "опенчат", "опен чат"},
        {"whitemax", "вайтмакс", "вайт макс"}, {"termux", "термукс"}, {"rustore", "рустор", "ру стор"},
        {"duckduckgo", "дак дак го", "дакдакго"}, {"firefox", "файрфокс", "фаерфокс"}, {"opera", "опера"},
        {"happ", "хап", "хапп"}, {"tailscale", "тейлскейл", "тейл скейл"}, {"shareit", "шарит", "шерит"},
        {"shizuku", "шизуку", "сидзуку"}, {"netshare", "нетшер", "нет шаре"}, {"smartertube", "смартертуб", "смартер туб"},
        {"smarttube", "смарттуб", "смарт туб"}, {"yowindow", "йовиндов", "йо виндов"},
        {"google maps", "гугл карты", "гугл картах"}, {"google play", "гугл плей", "плей маркет"},
        {"gmail", "джимейл", "джи мейл"}, {"outlook", "аутлук"}, {"zoom", "зум"}, {"steam", "стим"},
        {"samsung internet", "самсунг интернет"}, {"яндекс", "yandex"}, {"алиса", "alice"},
        {"настройки", "настройки телефона"}, {"камера", "камеру"}, {"галерея", "галерею"}
    };
    private static final java.util.regex.Pattern NON_NAME=java.util.regex.Pattern.compile("[^\\p{L}\\p{N}]");
    private static final java.util.Map<String,String> CANONICAL=names();
    private static java.util.Map<String,String> names(){java.util.Map<String,String> result=new java.util.HashMap<>();for(String[] row:NAMES)for(String name:row)result.put(compact(name),row[0]);return result;}
    static String compact(String value) { return NON_NAME.matcher(value).replaceAll(""); }
    public static java.util.List<String> alternatives(String label) {
        switch (app(label)) {
            case "telegram": return java.util.Arrays.asList("телеграм", "телеграмм");
            case "whatsapp": return java.util.Arrays.asList("ватсап", "ватсапп", "вотсап");
            case "chrome": return java.util.Arrays.asList("хром", "гугл хром");
            case "youtube": return java.util.Arrays.asList("ютуб", "ютюб");
            case "яндекс музыка": return java.util.Arrays.asList("яндекс музыка", "яндекс музыку", "yandex music");
            case "nimarkogram": return java.util.Arrays.asList("нимаркограм", "нимаркограмм", "нимаркограмму", "nimarkogramm");
            case "кион музыка": return java.util.Arrays.asList("кион музыку", "кион", "мтс музыка", "мтс музыку");
            default:
                String canonical = app(label);
                for (String[] row : NAMES) if (row[0].equals(canonical)) return java.util.Arrays.asList(row);
                String value = latinToRussian(label);
                return value.equals(label.toLowerCase(Locale.ROOT)) ? java.util.Collections.emptyList() : java.util.Arrays.asList(value);
        }
    }
    private static String latinToRussian(String source) {
        String value = source.toLowerCase(Locale.ROOT);
        String[][] pairs = {{"shch","щ"},{"sch","щ"},{"sh","ш"},{"ch","ч"},{"zh","ж"},{"kh","х"},{"th","т"},{"ph","ф"},{"ee","и"},{"oo","у"},{"qu","кв"},{"ai","ай"},{"ya","я"},{"yu","ю"},{"yo","йо"},{"ex","экс"}};
        for(String[] pair:pairs)value=value.replace(pair[0],pair[1]);
        String latin="abcdefghijklmnopqrstuvwxyz", russian="абкдефгхижклмнопкрстуввкиз";
        StringBuilder result=new StringBuilder();
        for(char c:value.toCharArray()){int i=latin.indexOf(c);if(i<0)result.append(c);else if(c=='x')result.append("кс");else result.append(russian.charAt(i));}
        return result.toString();
    }
    public static String app(String value) {
        String normalized = value.toLowerCase(Locale.ROOT).replace('ё', 'е').trim().replaceFirst("[.!?]+$", "");
        String canonical=CANONICAL.get(compact(normalized));if(canonical!=null)return canonical;
        switch (normalized) {
            case "телеграм": case "телеграмм": return "telegram";
            case "ватсап": case "ватсапп": case "вотсап": return "whatsapp";
            case "яндекс музыку": case "яндекс музыка": case "яндекс.музыка": case "yandex music": return "яндекс музыка";
            case "ютуб": case "ютюб": return "youtube";
            case "хром": case "гугл хром": case "google chrome": return "chrome";
            case "нимаркограм": case "нимаркограмм": case "нимаркограмму": case "nimarkogramm": return "nimarkogram";
            case "кион музыку": case "кион": case "мтс музыка": case "мтс музыку": return "кион музыка";
            default: return normalized;
        }
    }
    public static int percent(String value) {
        String normalized = value.toLowerCase(Locale.ROOT).replace('ё', 'е').trim().replaceAll("\\s+", " ");
        String[][] forms = {{"нуля","ноль"},{"одного","один"},{"одной","один"},{"двух","два"},{"трех","три"},{"четырех","четыре"},{"пяти","пять"},{"шести","шесть"},{"семи","семь"},{"восьми","восемь"},{"девяти","девять"},{"десяти","десять"},{"двадцати","двадцать"},{"тридцати","тридцать"},{"сорока","сорок"},{"пятидесяти","пятьдесят"},{"шестидесяти","шестьдесят"},{"семидесяти","семьдесят"},{"восьмидесяти","восемьдесят"},{"девяноста","девяносто"},{"ста","сто"}};
        String[] words = normalized.split(" ");
        for (int word = 0; word < words.length; word++) for (String[] form : forms) if (words[word].equals(form[0])) { words[word] = form[1]; break; }
        normalized = String.join(" ", words);
        String[] small = {"ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"};
        for (int i = 0; i < small.length; i++) if (normalized.equals(small[i])) return i;
        if (normalized.equals("сто")) return 100;
        String[] tens = {"двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"};
        for (int i = 0; i < tens.length; i++) {
            if (normalized.equals(tens[i])) return (i + 2) * 10;
            for (int unit = 1; unit < 10; unit++) if (normalized.equals(tens[i] + " " + small[unit])) return (i + 2) * 10 + unit;
        }
        return -1;
    }
}
