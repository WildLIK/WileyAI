package ru.wildlik.wileyai.mobile;

/**
 * Volatile snapshot of the LAST voice command's pipeline: recognition → routing →
 * screen observation → answer → speech. Statuses and numbers only — never the
 * recognized text, screen content or conversation history; never persisted to disk;
 * purely observational (nothing here re-runs STT, the model or tools). Holds no
 * references to sessions, services or listeners, so it cannot prolong their life.
 *
 * Ticket keying: stage records with a ticket other than the snapshot's own are
 * dropped, so a late callback of a cancelled or superseded command never pollutes
 * the current snapshot. Typed (non-voice) commands use the TICKETLESS (-1) slot.
 */
final class VoiceDiagnostics {
    private static final int TICKETLESS = -1;
    interface Sink { void event(int kind,long value); }
    private static volatile Sink sink;
    static void setSink(Sink value){sink=value;}
    private static void emit(int kind,long value){Sink target=sink;if(target!=null)try{target.event(kind,value);}catch(RuntimeException ignored){}}
    private static final VoiceDiagnostics INSTANCE = new VoiceDiagnostics();
    private volatile Snapshot snapshot = blank(TICKETLESS);

    record Snapshot(int ticket, String startedAt, String sttEngine, String sttOutcome, boolean sttText, long sttMs,
                    String routeKind, String routeHandler, String routeReason,
                    String observationStage, String observationOutcome, int observationMatches, String observationTarget,
                    String answerOutcome, String ttsOutcome) {
    }

    private VoiceDiagnostics() {}

    static VoiceDiagnostics get() { return INSTANCE; }

    private static Snapshot blank(int ticket) {
        return new Snapshot(ticket, "", "", "", false, 0, "", "", "", "", "", 0, "", "", "");
    }

    /** A new voice utterance begins; typed commands begin with the TICKETLESS slot. */
    static void begin(int ticket) {
        INSTANCE.snapshot = withStartedAt(blank(ticket), ticket, clock()); emit(0,0);
    }

    static void stt(int ticket, String engine, String outcome, boolean hasText, long ms) {
        Snapshot s = INSTANCE.snapshot;
        if (s.ticket != ticket) return;
        emit(1,Math.max(0,Math.min(ms,3600000))); emit(6,hasText?1:0); if(outcome!=null && outcome.contains("ошиб"))emit(5,0);
        INSTANCE.snapshot = new Snapshot(s.ticket, s.startedAt, engine, outcome, hasText, ms, s.routeKind, s.routeHandler, s.routeReason,
            s.observationStage, s.observationOutcome, s.observationMatches, s.observationTarget, s.answerOutcome, s.ttsOutcome);
    }

    static void route(String kind, String handler, String reason) {
        emit(2,0); Snapshot s = INSTANCE.snapshot;
        INSTANCE.snapshot = new Snapshot(s.ticket, s.startedAt, s.sttEngine, s.sttOutcome, s.sttText, s.sttMs, kind, handler, reason,
            s.observationStage, s.observationOutcome, s.observationMatches, s.observationTarget, s.answerOutcome, s.ttsOutcome);
    }

    static void observation(String stage, String outcome, int matches, String target) {
        Snapshot s = INSTANCE.snapshot;
        INSTANCE.snapshot = new Snapshot(s.ticket, s.startedAt, s.sttEngine, s.sttOutcome, s.sttText, s.sttMs, s.routeKind, s.routeHandler, s.routeReason,
            stage, outcome, matches, target, s.answerOutcome, s.ttsOutcome);
    }

    static void answer(int ticket, String outcome) {
        Snapshot s = INSTANCE.snapshot;
        if (s.ticket != ticket) return;
        emit(3,outcome!=null && outcome.contains("ошиб") ? 2 : outcome!=null && outcome.contains("отмен") ? 1 : 0);
        INSTANCE.snapshot = new Snapshot(s.ticket, s.startedAt, s.sttEngine, s.sttOutcome, s.sttText, s.sttMs, s.routeKind, s.routeHandler, s.routeReason,
            s.observationStage, s.observationOutcome, s.observationMatches, s.observationTarget, outcome, s.ttsOutcome);
    }

    static void tts(int ticket, String outcome) {
        emit(4,0); Snapshot s = INSTANCE.snapshot;
        if (s.ticket != ticket) return;
        INSTANCE.snapshot = new Snapshot(s.ticket, s.startedAt, s.sttEngine, s.sttOutcome, s.sttText, s.sttMs, s.routeKind, s.routeHandler, s.routeReason,
            s.observationStage, s.observationOutcome, s.observationMatches, s.observationTarget, s.answerOutcome, outcome);
    }

    /** TTS engine errors carry no command ticket; they always belong to the running snapshot. */
    static void ttsError(String outcome) {
        emit(5,0); Snapshot s = INSTANCE.snapshot;
        INSTANCE.snapshot = new Snapshot(s.ticket, s.startedAt, s.sttEngine, s.sttOutcome, s.sttText, s.sttMs, s.routeKind, s.routeHandler, s.routeReason,
            s.observationStage, s.observationOutcome, s.observationMatches, s.observationTarget, s.answerOutcome, outcome);
    }

    /** Compact multi-line view for the existing diagnostics dialog; statuses only. */
    static String summary() {
        Snapshot s = INSTANCE.snapshot;
        if (s.startedAt.isEmpty()) return "\nПоследняя голосовая команда: не начата.";
        StringBuilder out = new StringBuilder("\nПоследняя голосовая команда (").append(s.startedAt).append(")");
        out.append("\nРаспознавание: ").append(s.sttEngine).append(" · ").append(s.sttOutcome);
        if (s.sttMs > 0) out.append(" · ").append(s.sttMs).append(" мс");
        out.append("\nМаршрут: ").append(s.routeKind.isEmpty() ? "не определён" : s.routeKind);
        if (!s.routeHandler.isEmpty()) out.append(" · ").append(s.routeHandler);
        if (!s.routeReason.isEmpty()) out.append(" · ").append(s.routeReason);
        if (!s.observationStage.isEmpty()) {
            out.append("\nНаблюдение экрана: ").append(s.observationStage);
            if (!s.observationOutcome.isEmpty()) out.append(" · ").append(s.observationOutcome);
            if (s.observationMatches > 0) out.append(" · найдено элементов: ").append(s.observationMatches);
            if (!s.observationTarget.isEmpty()) out.append(" · цель: ").append(s.observationTarget);
        }
        if (!s.answerOutcome.isEmpty()) out.append("\nОтвет: ").append(s.answerOutcome);
        if (!s.ttsOutcome.isEmpty()) out.append("\nОзвучка: ").append(s.ttsOutcome);
        return out.toString();
    }

    private static Snapshot withStartedAt(Snapshot s, int ticket, String startedAt) {
        return new Snapshot(ticket, startedAt, s.sttEngine, s.sttOutcome, s.sttText, s.sttMs, s.routeKind, s.routeHandler, s.routeReason,
            s.observationStage, s.observationOutcome, s.observationMatches, s.observationTarget, s.answerOutcome, s.ttsOutcome);
    }

    private static String clock() {
        return java.time.LocalTime.now().withNano(0).toString();
    }
}
