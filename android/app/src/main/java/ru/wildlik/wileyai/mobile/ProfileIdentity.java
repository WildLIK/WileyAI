package ru.wildlik.wileyai.mobile;

import java.util.Locale;

/** Explicit questions about identity use the corresponding user-entered field. */
final class ProfileIdentity {
    static String answer(String request,String name,String address){
        if(request==null)return null;
        String text=request.toLowerCase(Locale.ROOT).replace('ё','е').trim().replaceAll("[?!.,]+$","").trim();
        if(text.matches("(?:скажи )?(?:как меня зовут|какое у меня имя|what is my name)"))
            return name.isBlank()?"Вы пока не указали своё имя в профиле.":"В профиле указано ваше имя: "+name+".";
        if(text.matches("(?:скажи )?(?:как ко мне обращаться|как ты должна ко мне обращаться)"))
            return address.isBlank()?"Вы пока не указали предпочтительное обращение в профиле.":"Предпочтительное обращение: "+address+".";
        return null;
    }
    static String context(String name,String address){
        return "\nИмя ассистента — Уайли. Имя пользователя "+(name.isBlank()?"не задано":"указано отдельно в профиле")+
            ". Предпочтительное обращение "+(address.isBlank()?"не задано":"может отличаться от имени пользователя")+". Не придумывай данные пользователя.";
    }
    private ProfileIdentity(){}
}
