package ru.wildlik.wileyai.mobile;

/** Human-readable labels without inventing a speaker's name, gender or timbre. */
public final class VoiceLabels {
    private VoiceLabels() {}
    public static String title(String id, int number) {
        return id != null && id.matches("[А-ЯЁA-Z][а-яёa-z]{1,30}") ? id : "Русский голос " + number;
    }
    public static String quality(int quality) {
        if (quality >= 400) return "Высокое качество по оценке движка";
        if (quality >= 300) return "Обычное качество по оценке движка";
        if (quality >= 100) return "Качество ниже среднего по оценке движка";
        return "Оценка качества не указана";
    }
}
