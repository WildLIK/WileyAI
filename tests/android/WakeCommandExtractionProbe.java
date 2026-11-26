package ru.wildlik.wileyai.mobile;

public final class WakeCommandExtractionProbe {
    private static final String NAME = WakePhrase.SHORT;

    public static void main(String[] args) {
        if (args.length > 0) {
            for (String arg : args) {
                String result = clean(arg);
                PhoneCommands.Action action = PhoneCommands.parse(result, true);
                System.out.println(result + "\t" + (action == null ? "unrouted" : action.kind + ":" + action.value));
            }
            return;
        }
        equal("сколько времени?", clean("Вайли, сколько времени?"));
        equal("включи музыку", clean("Окей, Уайли, включи музыку"));
        equal("сколько времени", clean("Окей Вайли сколько времени"));
        equal("включи музыку", clean("Уайли включи музыку"));
        equal("включи музыку", clean("Окей, уай ли — включи музыку"));
        equal("сколько времени", clean("Вай ли Уайли Вайли сколько времени"));
        equal("сколько времени", clean("вали сколько времени"));
        equal("включи музыку", clean("вади включи музыку"));
        equal("включи музыку", clean("Окей, вади, включи музыку"));
        equal("включи музыку", clean("Вайли, вади, включи музыку"));
        equal("", clean("Окей, Вайли! Уайли"));
        equal("вали отсюда", clean("вали отсюда"));
        equal("вади открой Telegram", clean("вади открой Telegram"));
        equal("вади включи песню счастье", clean("вади включи песню счастье"));
        equal("вади не включай музыку", clean("вади не включай музыку"));
        equal("вади, если интересно, включи музыку", clean("вади, если интересно, включи музыку"));
        equal("случайный текст Вайли включи музыку", clean("случайный текст Вайли включи музыку"));
        equal("найди приложение Вайли", clean("Вайли, найди приложение Вайли"));
        equal("вади", clean("вади"));
        equal("ВайлиАИ сколько времени", clean("ВайлиАИ сколько времени"));
        equal("сколько времени", clean("уали сколько времени", true));
        equal("сколько времени", clean("вале сколько времени", true));
        equal("включи музыку", clean("уали включи музыку", true));
        equal("включи музыку", clean("вале, включи музыку", true));
        equal("поставь на паузу", clean("байли поставь на паузу", true));
        equal("включи музыку", clean("айли, включи музыку", true));
        equal("", clean("уали", true));
        equal("Вале включи музыку", clean("Вале включи музыку", false));
        equal("Вале сколько времени", clean("Вале сколько времени", false));
        equal("Вале сколько времени", clean("Вале сколько времени", true, "привет помощник"));
        equal("уали не включай музыку", clean("уали не включай музыку", true));
        equal("вале открой браузер", clean("вале открой браузер", true));
        equal("вале сколько времени осталось до встречи", clean("вале сколько времени осталось до встречи", true));
        equal("вале сколько времени и включи музыку", clean("вале сколько времени и включи музыку", true));
        equal("вале сколько времени, если ехать до дома", clean("вале сколько времени, если ехать до дома", true));
        equal("расскажи, сколько времени нужно Вале", clean("расскажи, сколько времени нужно Вале", true));
        equal("Открой приложение Вале", clean("Вайли, Открой приложение Вале", true));
        equal("не открывай браузер", clean("Уайли, не открывай браузер", true));
        equal("не включай музыку", clean("Уайли, не включай музыку", true));
        route("Сколько времени?", "info:time");
        route("Включи музыку", "media:play");
        route("Выключи музыку", "media:pause");
        route("Сделай потише", "volume:down");
        route("Сделай погромче", "volume:up");
        route("Поставь на паузу", "media:pause");
        route("Продолжи воспроизведение", "media:play");
        route("Открой браузер", "open:браузер");
        route("Не открывай браузер", "");
        route("Не включай музыку", "");
        route("Вайли, Вайли", "");
        route("Например, открой браузер", "");
        route("«Включи музыку» — это пример", "");
        route("Мы обсуждали, как Уайли включает музыку", "");
        route("", "");
        route("ээ невнятно мм", "");
    }

    private static String clean(String raw) {
        return clean(raw, false);
    }

    private static String clean(String raw, boolean handoff) {
        return clean(raw, handoff, NAME);
    }

    private static String clean(String raw, boolean handoff, String phrase) {
        return WakePhrase.firstCommand(raw, phrase, candidate -> {
            PhoneCommands.Action command = PhoneCommands.parse(candidate, true);
            return command != null && (command.kind.equals("info") || command.kind.equals("media"));
        }, handoff);
    }

    private static void route(String raw, String expected) {
        PhoneCommands.Action action = PhoneCommands.parse(clean(raw, true), true);
        equal(expected, action == null ? "" : action.kind + ":" + action.value);
    }

    private static void equal(String expected, String result) {
        if (!expected.equals(result)) throw new AssertionError("Expected " + expected + ", got " + result);
    }
}
