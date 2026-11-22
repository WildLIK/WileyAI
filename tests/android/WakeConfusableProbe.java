package ru.wildlik.wileyai.mobile;

public class WakeConfusableProbe {
    private static String repair(String s){return WakePhrase.removeConfusableWake(s,WakePhrase.SHORT,x->PhoneCommands.parse(x,true)!=null);}
    private static void check(boolean b){if(!b)throw new AssertionError();}
    public static void main(String[] args){
        check(repair("вали").equals(""));
        String command=repair("вали включи музыку");check(command.equals("включи музыку"));
        PhoneCommands.Action a=PhoneCommands.parse(command,true);check(a!=null&&a.kind.equals("media"));
        check(repair("вали не включай музыку").equals("вали не включай музыку"));
        check(repair("вали как включить музыку").equals("вали как включить музыку"));
        check(repair("вали отсюда").equals("вали отсюда"));
        for(String prefix:new String[]{"", "Вайли, ", "Уайли ", "Уай ли, ", "Вай ли ", "Окей, Уай ли — "})
            for(String question:new String[]{"сколько времени?", "сколько сейчас времени", "который час?"}){
                PhoneCommands.Action time=PhoneCommands.parse(prefix+question,true);
                check(time!=null&&time.kind.equals("info")&&time.value.equals("time"));
            }
        check(PhoneCommands.parse("Уай ли сделай потише",true).value.equals("down"));
        check(PhoneCommands.parse("Вай ли включи музыку",true).kind.equals("media"));
        check(PhoneCommands.parse("Вайли, открой Telegram",true).value.equals("Telegram"));
        check(PhoneCommands.parse("Уайли не открывай браузер",true)==null);
        check(PhoneCommands.blockedVoice("Окей вай ли не открывай браузер")==1);
        check(PhoneCommands.blockedVoice("Вайли открой приложение")==2);
        check(PhoneCommands.parse("Уай ли включи",true)==null);
        check(PhoneCommands.parse("Вайлизация включи музыку",true)==null);
        check(PhoneCommands.blockedVoice("Почему не включается музыка?")==0);
        check(PhoneCommands.parse("Поставь музыку",true)==null || !PhoneCommands.parse("Поставь музыку",true).kind.equals("open"));
    }
}
