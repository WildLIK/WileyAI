package ru.wildlik.wileyai.mobile;

import java.util.Locale;

/** Speech is selected only after the player has verified its state. */
final class MediaSpeech {
    static String confirmed(String action, String request) {
        String text = request == null ? "" : request.toLowerCase(Locale.ROOT).replace('ё', 'е');
        if (action.equals("pause")) return text.matches(".*(?:останов|стоп).*" ) ? "Музыка остановлена." : "На паузе.";
        if (action.equals("play")) return text.matches(".*(?:продолж|возобнов|сними с паузы).*" ) ? "Продолжаю." : "Включаю музыку.";
        if (action.equals("next") || action.equals("previous")) return "Переключаю.";
        return "Позиция изменена.";
    }
    static String status(String title, String artist, String fallback) {
        String song = title == null ? "" : title.trim();
        String performer = artist == null ? "" : artist.trim();
        if (song.isEmpty()) return performer.isEmpty() ? fallback : performer + ".";
        return performer.isEmpty() ? song + "." : song + " — " + performer + ".";
    }
    static String volume(String action, int before, int after, String fallback) {
        if (after < before && (action.equals("down") || action.startsWith("down:"))) return "Убавила громкость.";
        if (after > before && (action.equals("up") || action.startsWith("up:"))) return "Прибавила громкость.";
        return fallback;
    }
    private MediaSpeech() {}
}
