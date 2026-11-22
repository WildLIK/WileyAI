package ru.wildlik.wileyai.mobile;

public final class MediaSpeechProbe {
    private static void eq(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
    public static void main(String[] args) {
        eq("Музыка остановлена.", MediaSpeech.confirmed("pause", "Останови музыку"));
        eq("На паузе.", MediaSpeech.confirmed("pause", "Поставь на паузу"));
        eq("Включаю музыку.", MediaSpeech.confirmed("play", "Включи музыку"));
        eq("Продолжаю.", MediaSpeech.confirmed("play", "Продолжи воспроизведение"));
        eq("Переключаю.", MediaSpeech.confirmed("next", "Следующая песня"));
        eq("Переключаю.", MediaSpeech.confirmed("previous", "Предыдущая песня"));
        eq("Убавила громкость.", MediaSpeech.volume("down", 5, 4, "5%"));
        eq("0%", MediaSpeech.volume("down", 0, 0, "0%"));
        eq("Трек — Исполнитель.", MediaSpeech.status("Трек", "Исполнитель", "Нет данных"));
        eq("Нет данных", MediaSpeech.status(null, null, "Нет данных"));
        if(MusicCatalogPolicy.rank("Мой микс",true,"mix")!=2)throw new AssertionError("personal mix");
        if(MusicCatalogPolicy.rank("Любимые треки",true,"likes")!=1)throw new AssertionError("liked tracks");
        for(String unsafe:new String[]{"Подкаст: мой микс","Реклама", "Мой микс подкастов", "Следующая песня"})if(MusicCatalogPolicy.rank(unsafe,true,"x")!=0)throw new AssertionError(unsafe);
        if(MusicCatalogPolicy.rank("Мой микс",false,"mix")!=0||MusicCatalogPolicy.rank("Мой микс",true,"")!=0)throw new AssertionError("missing playback or id");
        PhoneActionReply reply = (display, spoken) -> {
            eq("Подробный результат с названием и длительностью", display);
            eq("На паузе.", spoken);
        };
        reply.result("Подробный результат с названием и длительностью", "На паузе.");
    }
}
