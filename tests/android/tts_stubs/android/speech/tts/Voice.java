package android.speech.tts;
import java.util.Locale;
import java.util.Set;
public class Voice {
    public String getName(){return "ru-test";} public Locale getLocale(){return new Locale("ru");}
    public boolean isNetworkConnectionRequired(){return false;} public Set<String> getFeatures(){return Set.of();}
}
