package ru.wildlik.wileyai.mobile;

import java.util.Locale;

public final class ConversationMode {
    public static final int NONE=0,START=1,END=2;
    public static int waitMillis(boolean conversation,boolean followup,int shortSeconds,int longSeconds,int turns,long elapsed){
        if(turns>=20 || elapsed>=15*60*1000L || (!conversation&&!followup))return 0;
        return conversation?Math.max(10,Math.min(60,longSeconds))*1000:Math.max(3,Math.min(15,shortSeconds))*1000;
    }
    public static int parse(String text){
        if(text==null)return NONE;
        String value=text.toLowerCase(Locale.ROOT).replace('ё','е').replaceAll("[,.!?]"," ").trim().replaceAll("\\s+"," ");
        value=value.replaceFirst("^(?:окей (?:вайли|уайли|вай ли)|привет помощник|слушай помощник) ","");
        if(value.matches("давай поговорим|поговорим|начни разговор|режим разговора|включи режим разговора|хочу поговорить"))return START;
        if(value.matches("закончили|закончим|хватит разговаривать|хватит разговоров|закончить разговор|заверши разговор|стоп разговор|спасибо хватит|спасибо пока|выйди из режима разговора"))return END;
        return NONE;
    }
    private ConversationMode(){}
}
