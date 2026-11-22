package ru.wildlik.wileyai.mobile;

import java.util.Locale;

/** Only an explicit, present-tense user request may start an observation. */
public final class ScreenRequest {
    public enum Kind { NONE, OBSERVE, FIND, ACTION_REFUSED }
    public static Kind classify(String input){return classify(input,false);}
    public static Kind classify(String input,boolean screenAvailable){
        if(input==null)return Kind.NONE;String s=input.toLowerCase(Locale.ROOT).replace('ё','е').trim();
        if(s.startsWith("\"")||s.startsWith("«")||s.contains("```")||s.matches("(?s).*(?:не (?:смотри|читай|ищи|нажимай)|не надо|передумал|если |когда |он сказал|она сказала|расскажи как|объясни как|как работает|можно ли посмотреть|умеешь ли).*"))return Kind.NONE;
        boolean screen=s.matches("(?s).*(?:экран|передо мной|кнопк|поле поиска|здесь|тут|отсюда|что (?:у меня )?(?:сейчас )?(?:есть )?открыт|что можно выбрать|что ты видишь|какие кнопки).*" );
        if(s.matches("(?s).*(?:нажм|клик|прокрут|введи|впиши|тапни).*(?:кнопк|экран|на не[её]|на нее).*"))return Kind.ACTION_REFUSED;
        if(screen){
            if(s.matches("(?s).*(?:и|затем|потом)\\s+(?:открой|запусти|включи|выключи|нажми|введи|прокрути).*"))return Kind.ACTION_REFUSED;
            if(s.matches("(?s).*(?:где |найди|найти|есть ли |видишь ли |ты видишь |как отсюда попасть ).*(?:кнопк|поле|поиск|настрой|продолж|уведомлен).*")||s.matches("(?s).*(?:найди|найти|где |есть ли ).*(?:на экране|здесь|тут).*") )return Kind.FIND;
            if(s.matches("(?s).*(?:что (?:у меня )?(?:сейчас )?(?:есть )?(?:на экране|передо мной|открыт)|что отображается на экране|посмотри (?:на )?экран|покажи что на экране|опиши экран|какие (?:здесь |тут )?(?:есть )?кнопки|что ты видишь|покажи доступные кнопки|что можно выбрать).*"))return Kind.OBSERVE;
        }
        // A bare "find X" is ambiguous: with observation available the read-only screen path is preferred
        // over the app planner, whose find_app/open_app_settings can act when the label is not an application.
        if(screenAvailable&&s.matches("(?s)(?:найди|найти|где |покажи|есть ли ).*")&&!s.matches("(?s).*(?:приложени|программ|установлен|игр|песн|музык|трек|фильм|кино|видео|ютуб|youtube|интернет|браузер|сайт|скачай|удали|открой|запусти).*"))return Kind.FIND;
        return Kind.NONE;
    }
    private ScreenRequest(){}
}
