package ru.wildlik.wileyai.mobile;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Only complete, explicit user requests become local actions. */
public final class PhoneCommands {
    public static final class Action {
        public final String kind, value, target;
        Action(String kind, String value) { this(kind,value,""); }
        Action(String kind, String value, String target) { this.kind = kind; this.value = value; this.target = target; }
    }
    private PhoneCommands() {}

    public static Action parse(String input, boolean selectedPhone) {
        if (input == null || input.length() > 300 || input.matches("(?s).*[\\r\\n\"«»“”].*")) return null;
        String original = input.trim();
        String value = java.text.Normalizer.normalize(original, java.text.Normalizer.Form.NFKC).toLowerCase(Locale.ROOT).replace('ё', 'е').replaceAll("\\s+", " ");
        if (value.matches(".*\\b(?:не|никогда|если|например|расскажи|объясни)\\b.*")) return null;
        boolean named = value.matches(".*\\s+на (?:телефоне|смартфоне)[.! ]*$");
        if (!selectedPhone && !named) return null;
        if (value.matches(".*\\s+на (?:компьютере|пк)[.! ]*$")) return null;
        value = value.replaceFirst("\\s+на (?:телефоне|смартфоне)(?=[.! ]*$)", "");
        value = cleanRequest(value);
        Action media = MediaCommands.parse(cleanRequest(original.replaceFirst("(?iu)\\s+на (?:телефоне|смартфоне)(?=[.! ]*$)", "")));
        if (media != null) return media;
        String askTime="(?:(?:скажи|подскажи|покажи)(?: мне)?(?: пожалуйста)? )?";
        if (value.matches(askTime+"(?:(?:сейчас )?(?:сколько (?:сейчас )?(?:по )?(?:времени|время|часов)|который (?:сейчас )?час|какое (?:сейчас )?время|время|час)(?: сейчас)?|время (?:какое|сколько)(?: сейчас)?|по времени)")) return new Action("info", "time");
        if (value.matches("какая (?:сегодня )?дата|сегодня какая дата|какое сегодня число|какой сегодня день|покажи дату|дата")) return new Action("info", "date");
        if (value.matches("(?:сколько|какой) (?:осталось )?(?:заряд|заряда|зарядки|заряд батареи)|уровень (?:заряда|батареи)|сколько (?:сейчас )?процентов батареи|заряд батареи")) return new Action("info", "battery");
        if (value.matches("(?:пауза|стоп|останови(?:ть)? (?:музыку|воспроизведение|трек|песню)|поставь(?:ть)? (?:музыку|трек|песню) на паузу|приостанови(?:ть)?(?: музыку| воспроизведение)?)")) return new Action("media", "pause");
        if (value.matches("(?:включи(?:ть)? музыку|продолжи(?:ть)?(?: музыку| воспроизведение| трек| песню)?|возобнови(?:ть)? воспроизведение|воспроизведи музыку|сними с паузы)")) return new Action("media", "play");
        if (value.matches("(?:(?:включи(?:ть)?|переключи(?:ть)? на|поставь) )?(?:следующий (?:трек|трэк)|следующ(?:ая|ую) песн(?:я|ю))|пропусти (?:трек|песню)")) return new Action("media", "next");
        if (value.matches("(?:(?:включи(?:ть)?|переключи(?:ть)? на|поставь) )?(?:предыдущий (?:трек|трэк)|предыдущ(?:ая|ую) песн(?:я|ю))")) return new Action("media", "previous");
        String up = "(?:прибавь|прибавить|увеличь|увеличить|подними|поднять|добавь|добавить)";
        String down = "(?:убавь|убавить|уменьши|уменьшить|снизь|снизить|понизь|понизить)";
        if (value.matches("(?:(?:сделай|сделать|можно) )?(?:(?:немного|чуть|чуть-чуть) )?(?:по)?громче(?: музыку| звук)?|(?:сделай|сделать) (?:музыку|звук) (?:по)?громче|" + up + "(?: немного)?(?: громкость| громкости| звук| звука| музыку)")) return new Action("volume", "up");
        if (value.matches("(?:(?:сделай|сделать|можно) )?(?:(?:немного|чуть|чуть-чуть) )?(?:по)?тише(?: музыку| звук)?|(?:сделай|сделать) (?:музыку|звук) (?:по)?тише|" + down + "(?: немного)?(?: громкость| громкости| звук| звука| музыку)")) return new Action("volume", "down");
        if (value.matches("(?:какая (?:сейчас )?громкость\\??|текущая громкость|покажи громкость)")) return new Action("volume", "status");
        if (value.matches("(?:выключи(?:ть)?|отключи(?:ть)?|убери|убрать) (?:звук|громкость)|без звука")) return new Action("volume", "0");
        if (value.matches("(?:верни|вернуть|включи(?:ть)?) звук")) return new Action("volume", "restore");
        String setting = "(?:(?:установи(?:ть)?|сделай|сделать|поставь|поставить) )?(?:громкость|звук|музыку)(?: на| до)? ";
        if (value.matches(setting + "(?:максимум|максимальную|полную)|(?:на )?максимальную громкость")) return new Action("volume", "100");
        if (value.matches(setting + "(?:половину|пятьдесят)|(?:сделай |сделать )?(?:на ?)?половину (?:громкости|звука)")) return new Action("volume", "50");
        Matcher relative = Pattern.compile("(" + up + "|" + down + ") (?:громкость|звук)(?: музыки)? на (.+?)(?:\\s*%| процентов| процента| процент)?").matcher(value);
        if (relative.matches()) { int percent = number(relative.group(2)); if (percent >= 0) return new Action("volume", (relative.group(1).matches(up) ? "up:" : "down:") + percent); }
        if (value.matches("включи (?:яндекс[. ]*музык[ауы]?|yandex music)")) return new Action("open", "Яндекс Музыка");
        Matcher spokenVolume = Pattern.compile(setting + "(.+?)(?:\\s*%| процентов| процента| процент)?").matcher(value);
        if (spokenVolume.matches()) {
            int percent = number(spokenVolume.group(1));
            if (percent >= 0) return new Action("volume", Integer.toString(percent));
        }
        original = original.replaceFirst("(?iu)\\s+на (?:телефоне|смартфоне)(?=[.! ]*$)", "")
                ;
        original = cleanRequest(original);
        Matcher opening = Pattern.compile("(?:открой|открыть|запусти|запустить|включи|включить|зайди в|перейди в) (?:мне )?(?:приложение |программу |сайт )?(.+)", Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE).matcher(original);
        if (opening.matches()) return new Action("open", opening.group(1).trim());
        return null;
    }
    private static int number(String value) {
        if (value.matches("[0-9]{1,3}")) { int number = Integer.parseInt(value); return number <= 100 ? number : -1; }
        return SpokenNames.percent(value);
    }
    private static String cleanRequest(String value) {
        String cleaned = value.replaceFirst("(?iu)^(?:уайли|вайли|wiley)[,! ]+", "");
        for (int i = 0; i < 3; i++) cleaned = cleaned.replaceFirst("(?iu)^(?:а теперь|а еще|теперь|а|еще вопрос|еще|пожалуйста|можешь|можете|давай|будь добра)[, ]+", "");
        return cleaned.replaceFirst("(?iu)[, ]+пожалуйста[.!? ]*$", "").replaceFirst("[.!? ]+$", "").trim();
    }
}
