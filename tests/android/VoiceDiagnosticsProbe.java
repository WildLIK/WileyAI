package ru.wildlik.wileyai.mobile;

/** Pipeline diagnostics snapshot against simulated stage callbacks; no microphone, no LLM, no accessibility. */
public final class VoiceDiagnosticsProbe {
    static void check(boolean value) { if (!value) throw new AssertionError(); }

    public static void main(String[] args) {
        // 1. Successful screen query: every stage lands in one snapshot.
        VoiceDiagnostics.begin(1);
        VoiceDiagnostics.stt(1, "Vosk", "готово", true, 1400);
        VoiceDiagnostics.route("OBSERVE", "маршрутизатор экрана", "");
        VoiceDiagnostics.observation("проекция", "успешно", 2, "com.example.fixture");
        VoiceDiagnostics.answer(1, "получен");
        VoiceDiagnostics.tts(1, "завершена");
        String success = VoiceDiagnostics.summary();
        check(success.contains("Распознавание: Vosk · готово"));
        check(success.contains("Маршрут: OBSERVE · маршрутизатор экрана"));
        check(success.contains("Наблюдение экрана: проекция · успешно · найдено элементов: 2 · цель: com.example.fixture"));
        check(success.contains("Ответ: получен") && success.contains("Озвучка: завершена"));

        // 2/3/4. STT error, empty result and timeout share honest statuses.
        VoiceDiagnostics.begin(2); VoiceDiagnostics.stt(2, "GigaAM", "ошибка распознавания", false, 350);
        check(VoiceDiagnostics.summary().contains("GigaAM · ошибка распознавания"));
        VoiceDiagnostics.begin(3); VoiceDiagnostics.stt(3, "Vosk", "пустой результат (тишина, остановка или таймаут)", false, 15000);
        check(VoiceDiagnostics.summary().contains("пустой результат") && VoiceDiagnostics.summary().contains("15000 мс"));
        check(!VoiceDiagnostics.summary().contains("планировщик")); // no route without text

        // 6. Undefined intent: the router declined and the planner took over.
        VoiceDiagnostics.begin(4); VoiceDiagnostics.stt(4, "Vosk", "готово", true, 900);
        VoiceDiagnostics.route("", "планировщик", "не распознано как запрос к экрану");
        check(VoiceDiagnostics.summary().contains("Маршрут: не определён · планировщик · не распознано как запрос к экрану"));

        // 8/9/10/11/12. Observation outcomes map to distinct reasons.
        String[][] cases = {
            {"service_missing", "служба или исходное окно недоступны"},
            {"ambiguous_window", "служба или исходное окно недоступны"},
            {"app_permission", "экран защищён или приложение не разрешено"},
            {"window_changed", "окно изменилось или запрос отменён"},
            {"window_changed_or_revoked", "окно изменилось или запрос отменён"},
        };
        for (String[] item : cases) {
            VoiceDiagnostics.begin(5); VoiceDiagnostics.stt(5, "Vosk", "готово", true, 500);
            VoiceDiagnostics.route("FIND", "маршрутизатор экрана", "");
            VoiceDiagnostics.observation("проекция", item[1], 0, item[0]);
            check(VoiceDiagnostics.summary().contains("Наблюдение экрана: проекция · " + item[1] + " · цель: " + item[0]));
        }

        // 13. Model failure; 14. TTS failure.
        VoiceDiagnostics.begin(6); VoiceDiagnostics.stt(6, "Vosk", "готово", true, 400); VoiceDiagnostics.answer(6, "ошибка модели");
        check(VoiceDiagnostics.summary().contains("Ответ: ошибка модели"));
        VoiceDiagnostics.ttsError("ошибка озвучки");
        check(VoiceDiagnostics.summary().contains("Озвучка: ошибка озвучки"));

        // 15. Late callbacks of a finished command are dropped by ticket keying.
        VoiceDiagnostics.begin(7); VoiceDiagnostics.stt(7, "GigaAM", "готово", true, 700);
        VoiceDiagnostics.route("FIND", "маршрутизатор экрана", "");
        VoiceDiagnostics.observation("поиск элемента", "успешно", 1, "com.example.fixture");
        String before = VoiceDiagnostics.summary();
        VoiceDiagnostics.stt(6, "Vosk", "поздний статус", true, 0); // stale ticket from the previous command
        VoiceDiagnostics.answer(2, "поздний ответ"); VoiceDiagnostics.tts(2, "поздняя озвучка");
        check(VoiceDiagnostics.summary().equals(before));

        // A cancellation of the CURRENT command is recorded with its own ticket.
        VoiceDiagnostics.begin(8); VoiceDiagnostics.stt(8, "Vosk", "готово", true, 600);
        VoiceDiagnostics.route("OBSERVE", "маршрутизатор экрана", "");
        VoiceDiagnostics.answer(8, "отменён");
        check(VoiceDiagnostics.summary().contains("Ответ: отменён"));

        // 16. No sensitive content: statuses and numbers only.
        VoiceDiagnostics.begin(9); VoiceDiagnostics.stt(9, "Vosk", "готово", true, 300);
        VoiceDiagnostics.route("FIND", "маршрутизатор экрана", "");
        VoiceDiagnostics.observation("проекция", "успешно", 3, "com.example.fixture");
        VoiceDiagnostics.answer(9, "получен"); VoiceDiagnostics.tts(9, "завершена");
        String clean = VoiceDiagnostics.summary();
        for (String banned : new String[]{"пароль", "секретная", "переписк", "token", "cookie", "снимок экрана"})
            check(!clean.contains(banned));
        check(!clean.contains("«")); // the recognized phrase is never echoed into diagnostics

        // Typed commands use the TICKETLESS slot and supersede the voice snapshot.
        VoiceDiagnostics.begin(-1); VoiceDiagnostics.stt(-1, "Vosk", "готово", true, 200);
        VoiceDiagnostics.route("FIND", "маршрутизатор экрана", "");
        VoiceDiagnostics.answer(-1, "получен");
        check(VoiceDiagnostics.summary().contains("Маршрут: FIND"));
        VoiceDiagnostics.answer(8, "поздний ответ"); // voice ticket no longer matches
        check(!VoiceDiagnostics.summary().contains("отменён"));

        System.out.println("Voice diagnostics snapshot checks passed");
    }
}
