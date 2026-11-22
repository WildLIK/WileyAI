package ru.wildlik.wileyai.mobile;

public class WakePrefixProbe {
    private static void eq(String actual,String expected){if(!actual.equals(expected))throw new AssertionError(actual+" != "+expected);}
    public static void main(String[] args){
        eq(WakePhrase.removeLeadingWake("Вайли, включи музыку",WakePhrase.SHORT),"включи музыку");
        eq(WakePhrase.removeLeadingWake("Окей, Вайли, открой настройки",WakePhrase.SHORT),"открой настройки");
        eq(WakePhrase.removeLeadingWake("Вайли",WakePhrase.SHORT),"");
        eq(WakePhrase.removeLeadingWake("Вайлизация музыки",WakePhrase.SHORT),"Вайлизация музыки");
        eq(WakePhrase.removeLeadingWake("не включай музыку",WakePhrase.SHORT),"не включай музыку");
        java.util.function.Predicate<String> music=s->s.equals("включи музыку");
        eq(WakePhrase.removeConfusableWake("вали включи музыку",WakePhrase.SHORT,music),"включи музыку");
        eq(WakePhrase.removeConfusableWake("вали не включай музыку",WakePhrase.SHORT,music),"вали не включай музыку");
        eq(WakePhrase.removeConfusableWake("вали отсюда",WakePhrase.SHORT,music),"вали отсюда");
        eq(WakePhrase.removeConfusableWake("вали включи музыку","привет помощник",music),"вали включи музыку");
    }
}
