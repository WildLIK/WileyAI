package ru.wildlik.wileyai.mobile;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Only complete, explicit user requests become local actions. */
public final class PhoneCommands {
    public static final class Action {
        public final String kind, value;
        Action(String kind, String value) { this.kind = kind; this.value = value; }
    }
    private PhoneCommands() {}

    public static Action parse(String input, boolean selectedPhone) {
        if (input == null || input.length() > 300 || input.matches("(?s).*[\\r\\n\"«»“”].*")) return null;
        String original = input.trim();
        String value = original.toLowerCase(Locale.ROOT).replace('ё', 'е');
        if (value.matches(".*\\b(?:не|никогда|если|например|расскажи|объясни)\\b.*")) return null;
        boolean named = value.matches(".*\\s+на (?:телефоне|смартфоне)[.! ]*$");
        if (!selectedPhone && !named) return null;
        if (value.matches(".*\\s+на (?:компьютере|пк)[.! ]*$")) return null;
        value = value.replaceFirst("\\s+на (?:телефоне|смартфоне)(?=[.! ]*$)", "");
        value = value.replaceFirst("^(?:уайли[,! ]+)?(?:пожалуйста[, ]+)?", "").replaceFirst("[.! ]+$", "");
        if (value.matches("(?:пауза|останови музыку|поставь музыку на паузу|приостанови музыку)")) return new Action("media", "pause");
        if (value.matches("(?:включи музыку|продолжи музыку|продолжи воспроизведение|воспроизведи музыку)")) return new Action("media", "play");
        if (value.matches("(?:следующий трек|следующая песня|включи следующий трек)")) return new Action("media", "next");
        if (value.matches("(?:предыдущий трек|предыдущая песня|включи предыдущий трек)")) return new Action("media", "previous");
        if (value.matches("(?:громче|сделай громче|прибавь громкость|увеличь громкость)")) return new Action("volume", "up");
        if (value.matches("(?:тише|сделай тише|сделай потише|убавь громкость|уменьши громкость)")) return new Action("volume", "down");
        if (value.matches("(?:какая громкость\\??|текущая громкость|покажи громкость)")) return new Action("volume", "status");
        if (value.matches("включи (?:яндекс[. ]*музык[ауы]?|yandex music)")) return new Action("open", "Яндекс Музыка");
        Matcher volume = Pattern.compile("(?:установи |сделай |поставь )?громкость(?: на)? ([0-9]{1,3})(?:\\s*%| процентов| процента)?").matcher(value);
        if (volume.matches() && Integer.parseInt(volume.group(1)) <= 100) return new Action("volume", volume.group(1));
        original = original.replaceFirst("(?iu)\\s+на (?:телефоне|смартфоне)(?=[.! ]*$)", "")
                .replaceFirst("(?iu)^(?:уайли[,! ]+)?(?:пожалуйста[, ]+)?", "").replaceFirst("[! ]+$", "");
        Matcher opening = Pattern.compile("(?:открой|запусти) (?:приложение |программу |сайт )?(.+)", Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE).matcher(original);
        if (opening.matches()) return new Action("open", opening.group(1).trim());
        return null;
    }
}
