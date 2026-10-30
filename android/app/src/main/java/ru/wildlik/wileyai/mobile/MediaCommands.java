package ru.wildlik.wileyai.mobile;

import java.util.Locale;
import java.util.regex.*;

/** Complete media requests only. Search text is data and is never parsed again as an action. */
public final class MediaCommands {
    private static final String VIDEO = "(?:ютуб(?:е|а)?|ютюб(?:е|а)?|youtube|ютуб ревансед|youtube revanced|ревансед)";
    private static final String MUSIC = "(?:кион(?: музык[аеуы])?|мтс музык[аеуы]|музык[аеуы]|плеер[ае]?)";
    static PhoneCommands.Action parse(String input) {
        String text = input.trim(), target = "";
        Matcher prefix = Pattern.compile("^("+VIDEO+"|"+MUSIC+")[,: ]+(.+)$", Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE).matcher(text);
        if (prefix.matches()) { target = target(prefix.group(1)); text = prefix.group(2).trim(); }
        Matcher suffix = Pattern.compile("^(.+?) (?:в|на) ("+VIDEO+"|"+MUSIC+")$", Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE).matcher(text);
        if (suffix.matches()) { String named = target(suffix.group(2)); if (!target.isEmpty() && !target.equals(named)) return null; target = named; text = suffix.group(1).trim(); }
        Matcher inner = Pattern.compile("^(найди|найти|поищи|покажи|включи|включить|поставь|поставить|воспроизведи) (?:в|на) ("+VIDEO+"|"+MUSIC+") (.+)$", Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE).matcher(text);
        if (inner.matches()) { String named = target(inner.group(2)); if (!target.isEmpty() && !target.equals(named)) return null; target = named; text = inner.group(1)+" "+inner.group(3); }
        Matcher namedPause=Pattern.compile("^(поставь|останови|продолжи|перемотай|включи) ("+VIDEO+"|"+MUSIC+")( на паузу| сначала)?$",Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE).matcher(text);
        if(namedPause.matches()){String named=target(namedPause.group(2));if(!target.isEmpty()&&!target.equals(named))return null;target=named;text=namedPause.group(1)+(named.equals("youtube")?" видео":" музыку")+(namedPause.group(3)==null?"":namedPause.group(3));}
        String value = text.toLowerCase(Locale.ROOT).replace('ё','е');
        if(!target.isEmpty() && value.matches(".*(?:громк|громче|тише|звук).*")) { PhoneCommands.Action volume=PhoneCommands.parse(text,true); if(volume!=null&&volume.kind.equals("volume"))return volume; }
        Matcher search = Pattern.compile("^(найди|найти|поищи|покажи|включи|включить|поставь|поставить|воспроизведи) (?:мне )?(?:(песню|трек|музыку|видео|ролик) )?(.+)$", Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE).matcher(text);
        if (search.matches() && (search.group(2) != null || !target.isEmpty())) {
            String noun = search.group(2) == null ? "" : search.group(2).toLowerCase(Locale.ROOT), query = search.group(3).trim();
            // Plain play/pause and volume requests must not become song searches.
            boolean transport = query.matches("(?iu)(?:на паузу|с паузы|сначала|дальше|продолжи|пауза|стоп|следующ(?:ий|ую)|предыдущ(?:ий|ую)|громче|тише|звук|громкость)(?: .*|$)") || query.matches("(?iu)(?:музык[ау]|видео|ролик)");
            if (!transport && !query.isEmpty() && query.length() <= 200) {
                if (target.isEmpty()) target = noun.matches("видео|ролик") ? "youtube" : "music";
                String kind = search.group(1).toLowerCase(Locale.ROOT).matches("найди|найти|поищи|покажи") ? "media_search" : "media_play_search";
                return new PhoneCommands.Action(kind, query, target);
            }
        }
        if (target.isEmpty() && value.matches(".*(?:видео|ролик).*")) target = "youtube";
        if (value.matches("(?:пауза|стоп|останови(?:ть)?(?: музыку| видео| ролик| воспроизведение| трек| песню)?|поставь(?:ть)?(?: музыку| видео| ролик| трек| песню)? на паузу|приостанови(?:ть)?(?: музыку| видео| воспроизведение)?)")) return action("pause",target);
        if (value.matches("(?:включи(?:ть)? (?:музыку|видео)|воспроизведи(?: музыку| видео)?|продолжи(?:ть)?(?: музыку| видео| воспроизведение| трек| песню)?|возобнови(?:ть)?(?: музыку| видео| воспроизведение)?|сними(?: музыку| видео)? с паузы)")) return action("play",target);
        if (value.matches("(?:(?:включи(?:ть)?|переключи(?:ть)? на|поставь|покажи) )?(?:следующий (?:трек|трэк|ролик)|следующ(?:ая|ую) песн(?:я|ю)|следующее видео)|пропусти (?:трек|песню|видео|ролик)")) return action("next",target);
        if (value.matches("(?:(?:включи(?:ть)?|переключи(?:ть)? на|поставь|покажи) )?(?:предыдущий (?:трек|трэк|ролик)|предыдущ(?:ая|ую) песн(?:я|ю)|предыдущее видео)")) return action("previous",target);
        if (value.matches("что (?:сейчас )?(?:играет|воспроизводится)|какая (?:сейчас )?(?:песня|музыка)(?: играет)?|что за (?:песня|трек)|какое (?:сейчас )?видео(?: играет)?|состояние плеера")) return action("status",target);
        if (value.matches("(?:начни|начать|включи|включить|перемотай|перемотать)(?: трек| песню| видео| ролик)? (?:сначала|на начало)|в начало")) return action("position:0",target);
        Matcher seek = Pattern.compile("^(?:перемотай|перемотать|промотай|промотать)(?: музыку| видео| трек| ролик)?(?: (вперед|назад))? на (.+?)(?: (вперед|назад))?$").matcher(value);
        if (seek.matches()) {
            String direction = seek.group(1) == null ? seek.group(3) : seek.group(1); if (seek.group(1) != null && seek.group(3) != null && !seek.group(1).equals(seek.group(3))) return null;
            long millis = time(seek.group(2)); if (millis < 0) return null;
            return action(direction == null ? "position:"+millis : "seek:"+(direction.equals("назад") ? -millis : millis),target);
        }
        return null;
    }
    private static PhoneCommands.Action action(String verb,String target) { return new PhoneCommands.Action("media",verb,target); }
    private static String target(String text) { return text.toLowerCase(Locale.ROOT).matches(VIDEO) ? "youtube" : "music"; }
    static long time(String input) {
        if (input.matches("[0-9]{1,2}:[0-5][0-9](?::[0-5][0-9])?")) { String[] parts=input.split(":"); long seconds=0; for(String part:parts) seconds=seconds*60+Integer.parseInt(part); return seconds <= 86400 ? seconds*1000 : -1; }
        if (input.equals("минуту")) return 60000;
        if (input.equals("полминуты")) return 30000;
        Matcher unit=Pattern.compile("(.+?) (секунд(?:а|у|ы)?|минут(?:а|у|ы)?)").matcher(input);
        if (!unit.matches()) return -1;
        String number=unit.group(1); int n=number.matches("[0-9]{1,5}") ? Integer.parseInt(number) : SpokenNames.percent(number);
        long seconds=(long)n*(unit.group(2).startsWith("минут")?60:1); return n>=0 && seconds<=86400 ? seconds*1000 : -1;
    }
    private MediaCommands() {}
}
