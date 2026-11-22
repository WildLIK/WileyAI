package ru.wildlik.wileyai.mobile;

import java.util.Locale;

/** Accept only explicit, playable music collections; never infer from a partial match. */
final class MusicCatalogPolicy {
    static int rank(String title,boolean playable,String id){
        if(!playable||id==null||id.trim().isEmpty()||title==null)return 0;
        String text=title.toLowerCase(Locale.ROOT).replace('ё','е').trim().replaceAll("\\s+"," ");
        if(text.matches("мой микс|моя волна|my mix|my supermix"))return 2;
        if(text.matches("любимые треки|избранные треки|liked songs"))return 1;
        return 0;
    }
    private MusicCatalogPolicy(){}
}
