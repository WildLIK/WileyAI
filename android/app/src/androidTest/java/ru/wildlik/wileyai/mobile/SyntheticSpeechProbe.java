package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.Context;
import android.speech.tts.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.JSONObject;
import org.vosk.*;

/** Explicit opt-in device check. Synthesizes a public phrase to a file; never records the microphone. */
final class SyntheticSpeechProbe {
    static String run(Instrumentation runner, Context context) throws Exception {
        return run(runner, context, 0);
    }
    static String wake(Instrumentation runner, Context context, boolean negative) throws Exception { return run(runner, context, negative ? 2 : 1); }
    static String conversation(Instrumentation runner,Context context)throws Exception{return run(runner,context,3);}
    private static String run(Instrumentation runner, Context context, int mode) throws Exception {
        Path modelPath = VerifiedModelInstaller.active(context.getFilesDir().toPath().resolve("speech-models"));
        if (modelPath == null) throw new AssertionError("Сначала установите русский комплект через приложение");
        TextToSpeech[] tts = new TextToSpeech[1]; AtomicReference<String> failure = new AtomicReference<>();
        AtomicReference<Voice> chosen = new AtomicReference<>(); CountDownLatch ready = new CountDownLatch(1), done = new CountDownLatch(1);
        Path wav = context.getCacheDir().toPath().resolve("wiley-synthetic-speech-probe.wav");
        try {
            String selectedEngine = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE).getString("offline_engine", "");
            runner.runOnMainSync(() -> tts[0] = new TextToSpeech(context, status -> {
                if (status != TextToSpeech.SUCCESS) failure.set("Не удалось запустить TTS"); ready.countDown();
            }, selectedEngine.isEmpty() ? null : selectedEngine));
            if (!ready.await(20, TimeUnit.SECONDS) || failure.get() != null) throw new AssertionError("TTS: " + failure.get());
            List<Voice> voices = new ArrayList<>();
            for (Voice voice : tts[0].getVoices()) if (voice.getLocale().getLanguage().equals("ru") && !voice.isNetworkConnectionRequired()
                && (voice.getFeatures() == null || !voice.getFeatures().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED))) voices.add(voice);
            voices.sort(Comparator.comparing(Voice::getName));
            if (voices.isEmpty()) throw new AssertionError("Русский офлайн-голос не установлен");
            chosen.set(voices.get(0));
            tts[0].setOnUtteranceProgressListener(new UtteranceProgressListener() {
                public void onStart(String id) {}
                public void onDone(String id) { done.countDown(); }
                public void onError(String id) { failure.set("Ошибка синтеза"); done.countDown(); }
            });
            String phrase = mode == 0 ? "Громкость пятьдесят процентов" : mode == 1 ? "Окей Вайли" : mode==3?"Окей Вайли давай поговорим":"Окей";
            if (tts[0].setVoice(chosen.get()) != TextToSpeech.SUCCESS || tts[0].synthesizeToFile(phrase, null, wav.toFile(), "wiley-probe") != TextToSpeech.SUCCESS)
                throw new AssertionError("TTS не принял синтез в файл");
            if (!done.await(30, TimeUnit.SECONDS) || failure.get() != null) throw new AssertionError("Синтез: " + failure.get());
            byte[] bytes = Files.readAllBytes(wav); ByteBuffer data = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
            if (bytes.length < 44 || data.getInt(0) != 0x46464952 || data.getInt(8) != 0x45564157) throw new AssertionError("Ожидался WAV RIFF");
            int rate = 0, audioStart = -1, audioBytes = 0;
            for (int pos = 12; pos + 8 <= bytes.length;) {
                int id = data.getInt(pos), length = data.getInt(pos + 4); if (length < 0 || length > bytes.length - pos - 8) throw new AssertionError("Некорректный WAV");
                if (id == 0x20746d66) {
                    if (length < 16 || data.getShort(pos + 8) != 1 || data.getShort(pos + 10) != 1 || data.getShort(pos + 22) != 16) throw new AssertionError("Нужен mono PCM16 WAV");
                    rate = data.getInt(pos + 12);
                } else if (id == 0x61746164) { audioStart = pos + 8; audioBytes = length; }
                pos += 8 + length + (length & 1);
            }
            if (rate < 8000 || rate > 96000 || audioStart < 0 || audioBytes < rate) throw new AssertionError("Нет звука в тестовом WAV");
            short[] pcm = new short[audioBytes / 2]; for (int i = 0; i < pcm.length; i++) pcm[i] = data.getShort(audioStart + i * 2);
            short[] sampled = new short[(int)((long)pcm.length * 16000 / rate)];
            for (int i = 0; i < sampled.length; i++) {
                double position = (double)i * rate / 16000; int left = Math.min((int)position, pcm.length - 1), right = Math.min(left + 1, pcm.length - 1);
                sampled[i] = (short)Math.round(pcm[left] + (pcm[right] - pcm[left]) * (position - left));
            }
            String text; double confidence = 1;
            try (Model model = new Model(modelPath.toString()); Recognizer recognizer = mode == 0 ? new Recognizer(model, 16000) : new Recognizer(model, 16000, WakeVocabulary.grammar(model, WakePhrase.DEFAULT))) {
                recognizer.setWords(true); recognizer.acceptWaveForm(sampled, sampled.length); JSONObject decoded = new JSONObject(recognizer.getFinalResult()); text = decoded.optString("text");
                org.json.JSONArray words = decoded.optJSONArray("result"); if (words == null || words.length() == 0) confidence = 0; else for (int i = 0; i < words.length(); i++) confidence = Math.min(confidence, words.getJSONObject(i).optDouble("conf",0));
            }
            if (mode != 0) { boolean found = mode==3?WakePhrase.conversation(WakePhrase.DEFAULT,text,confidence):WakePhrase.matches(WakePhrase.DEFAULT, text, confidence); if (found != (mode == 1||mode==3)) throw new AssertionError("Wake probe: " + text + " confidence=" + confidence); return new JSONObject().put("source",phrase).put("recognized",text).put("minimum_confidence",confidence).put("triggered",found).put("microphone_used",false).toString(); }
            PhoneCommands.Action command = PhoneCommands.parse(text, true);
            if (command == null || !command.kind.equals("volume") || !command.value.equals("50")) throw new AssertionError("Распознано: " + text);
            Files.copy(wav, context.getCacheDir().toPath().resolve("wiley-synthetic-speech-sample.wav"), StandardCopyOption.REPLACE_EXISTING);
            return new JSONObject().put("engine", selectedEngine.isEmpty() ? tts[0].getDefaultEngine() : selectedEngine).put("voice", chosen.get().getName()).put("source_rate", rate)
                .put("samples_16000", sampled.length).put("recognized", text).put("command", "volume:50").put("executed", false).put("microphone_used", false).toString();
        } finally { if (tts[0] != null) runner.runOnMainSync(tts[0]::shutdown); Files.deleteIfExists(wav); }
    }
    private SyntheticSpeechProbe() {}
}
