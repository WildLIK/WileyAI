package ru.wildlik.wileyai.mobile;

import com.sun.jna.NativeLibrary;
import org.vosk.Model;

/** Do not let Vosk silently drop unknown words and reduce a wake phrase to one common word. */
final class WakeVocabulary {
    static boolean contains(Model model, String word) {
        return NativeLibrary.getInstance("vosk").getFunction("vosk_model_find_word").invokeInt(new Object[]{model.getPointer(), word}) >= 0;
    }
    static String grammar(Model model, String phrase) {
        org.json.JSONArray grammar = new org.json.JSONArray();
        for (String candidate : WakePhrase.decoderPhrases(phrase)) {
            boolean known = true; for (String word : candidate.split(" ")) if (!contains(model, word)) known = false;
            if (known) { grammar.put(candidate); if(contains(model,"давай") && contains(model,"поговорим")) grammar.put(candidate+" давай поговорим"); }
        }
        if (grammar.length() == 0) throw new IllegalArgumentException("Wake phrase is not in the installed vocabulary");
        return grammar.put("[unk]").toString();
    }
    private WakeVocabulary() {}
}
