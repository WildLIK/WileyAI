import ru.wildlik.wileyai.mobile.PhoneCommands;

public final class PhoneCommandsProbe {
    private static void is(String input, boolean phone, String kind, String value) {
        PhoneCommands.Action a = PhoneCommands.parse(input, phone);
        if (a == null || !a.kind.equals(kind) || !a.value.equals(value)) throw new AssertionError(input);
    }
    private static void not(String input, boolean phone) {
        if (PhoneCommands.parse(input, phone) != null) throw new AssertionError(input);
    }
    public static void main(String[] args) {
        is("Открой YouTube на телефоне", false, "open", "YouTube");
        is("Открой https://example.com/Case", true, "open", "https://example.com/Case");
        is("Громкость 50 на телефоне", false, "volume", "50");
        is("Следующий трек", true, "media", "next");
        is("Какая сейчас громкость?", true, "volume", "status");
        is("Уайли, пожалуйста, сделай громче", true, "volume", "up");
        is("Громкость 0 процентов", true, "volume", "0");
        is("Громкость 100%", true, "volume", "100");
        is("Громкость пятьдесят процентов", true, "volume", "50");
        is("Установи громкость на двадцать пять", true, "volume", "25");
        is("Громкость сто", true, "volume", "100");
        is("Открой Telegram", true, "open", "Telegram");
        is("Включи музыку на телефоне", false, "media", "play");
        is("Включи яндекс музыку на телефоне", false, "open", "Яндекс Музыка");
        is("прибавить громкость", true, "volume", "up");
        is("Сколько сейчас времени?", true, "info", "time");
        is("Какая сегодня дата?", true, "info", "date");
        is("Уровень заряда", true, "info", "battery");
        is("Уайли, можешь сделать погромче, пожалуйста?", true, "volume", "up");
        is("увеличь громкость на десять процентов", true, "volume", "up:10");
        is("убавь звук на 15%", true, "volume", "down:15");
        is("сделать громкость до пятидесяти процентов", true, "volume", "50");
        is("поставь громкость на половину", true, "volume", "50");
        is("выключить звук", true, "volume", "0");
        is("верни звук", true, "volume", "restore");
        is("сделай громкость на максимум", true, "volume", "100");
        is("можешь открыть Телеграм пожалуйста", true, "open", "Телеграм");
        is("Открой КИОН Музыку", true, "open", "КИОН Музыку");
        is("включить следующую песню", true, "media", "next");
        is("переключи на предыдущий трек", true, "media", "previous");
        not("Включи музыку на компьютере", true);
        not("Открой YouTube", false);
        not("Не открывай YouTube на телефоне", false);
        not("Если скажу открой YouTube на телефоне", false);
        not("Открой YouTube\nна телефоне", false);
        not("Громкость 999 на телефоне", false);
        not("Открой Telegram на компьютере", true);
        not("Не открой Telegram", true);
        not("Например открой Telegram", true);
        not("Открой «Telegram»", true);
        not("Громкость -1", true);
        not("Громкость 101", true);
        not("Громкость сто один", true);
        not("Не делай громкость пятьдесят", true);
        not("Если захочу прибавить громкость", true);
        not("прибавь громкость на сто один процент", true);
        not("прибавь громкость и открой Телеграм", true);
        System.out.println("Phone command routing passed");
    }
}
