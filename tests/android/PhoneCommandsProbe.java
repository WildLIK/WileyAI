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
        is("Включи музыку на телефоне", false, "media", "play");
        is("Включи яндекс музыку на телефоне", false, "open", "Яндекс Музыка");
        not("Включи музыку на компьютере", true);
        not("Открой YouTube", false);
        not("Не открывай YouTube на телефоне", false);
        not("Если скажу открой YouTube на телефоне", false);
        not("Открой YouTube\nна телефоне", false);
        not("Громкость 999 на телефоне", false);
        System.out.println("Phone command routing passed");
    }
}
