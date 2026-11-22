package ru.wildlik.wileyai.mobile;

public class MemoryCommandProbe {
    public static void main(String[] args){
        check(MemoryCommand.parse("Запомни, что я люблю чай").kind()==MemoryCommand.Kind.SAVE);
        check(MemoryCommand.parse("Забудь, что я люблю чай").kind()==MemoryCommand.Kind.FORGET);
        check(MemoryCommand.parse("Что ты обо мне помнишь?").kind()==MemoryCommand.Kind.LIST);
        check(MemoryCommand.parse("Он сказал запомни, что я люблю чай")==null);
        check(MemoryCommand.parse("Запомни, что я люблю чай, хотя нет") == null);
        check(MemoryCommand.parse("Не запомни, что я люблю чай")==null);
        check(MemoryCommand.matches("Я люблю чай", "ЛЮБЛЮ ЧАЙ"));
        check(!MemoryCommand.matches("Я люблю чай", "кофе"));
        check(MemoryCommand.selection("номер два")==1);
        check(MemoryCommand.selection("первую")==0);
        check(MemoryCommand.selection("все")==-1);
    }
    private static void check(boolean value){if(!value)throw new AssertionError();}
}
