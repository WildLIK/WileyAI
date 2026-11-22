package ru.wildlik.wileyai.mobile;

import java.util.Locale;
import java.text.Normalizer;

/** Conservative local screen projection. Unmarked personal data cannot be detected reliably. */
public final class ScreenPrivacy {
    public static boolean trustedPackage(String pkg,String own){return pkg!=null && (pkg.equals(own)||pkg.equals("com.android.settings"));}
    public static boolean protectedName(String value){
        if(value==null)return true;String s=value.toLowerCase(Locale.ROOT);
        return s.matches("(?s).*(?:password|passcode|passphrase|pinentry|credential|authenticat|payment|billing|wallet|bank|biometric|telegram|whatsapp|messenger|signal|gmail|contacts|gallery|парол|плат[её]ж|банк|авторизац|подтвержден|секрет|код доступа|переписк|контакт|галере).* ".trim());
    }
    public static boolean sensitive(CharSequence value){
        if(value==null)return false;if(value.length()>256)return true;String s=Normalizer.normalize(value.toString(),Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        return protectedName(s)||s.matches("(?s).*(?:\\b(?:pin|otp|cvv|cvc|iban|ssn)\\b|[0-9]{4}|[0-9][0-9 .-]{5,}[0-9]|@|https?://|[•●*]{3}|пароль|код подтверж|одноразов|номер карт|реквизит|сч[её]т|баланс|адрес|телефон|почта|фамили|паспорт|аккаунт|уч[её]тн|личн.*данн).*" );
    }
    public static String label(CharSequence text){
        if(text==null||text.length()>64)return "";
        String s=Normalizer.normalize(text.toString(),Normalizer.Form.NFKC).trim().replaceAll("\\s+"," ");
        if(s.isEmpty()||s.length()>64||sensitive(s))return "";
        // No digits, links, addresses, control characters or instruction syntax.
        if(!s.matches("[\\p{L}\\p{M}][\\p{L}\\p{M} ._-]{0,63}")||s.split(" ").length>5)return "";
        String lower=s.toLowerCase(Locale.ROOT);
        if(lower.matches("(?s).*(?:игнорир|инструкц|системн.*промпт|отправь|перешли|скажи мне|выполни|открой|запусти|ignore|instruction|system prompt|send |execute|run command).*"))return "";
        if(s.matches("[\\p{Lu}][\\p{Ll}]+ [\\p{Lu}][\\p{Ll}]+"))return "";
        return s;
    }
    public static String query(String text){
        if(text==null)return "";String s=Normalizer.normalize(text,Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        return s.replaceAll("[^\\p{L}\\p{M} -]"," ").replaceAll("\\s+"," ").trim();
    }
    public static boolean matches(String label,String query){
        String s=query(label);String q=query(query);if(s.isEmpty()||q.isEmpty())return false;
        if(s.equals(q)||q.contains(s))return true;
        for(String w:s.split(" "))if(w.length()>=4)for(String x:q.split(" "))if(x.length()>=4&&(w.startsWith(x)||x.startsWith(w)||w.substring(0,Math.min(5,w.length())).equals(x.substring(0,Math.min(5,x.length())))))return true;
        return false;
    }
    private ScreenPrivacy(){}
}
