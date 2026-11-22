package ru.wildlik.wileyai.mobile;

import android.os.SystemClock;
import java.util.concurrent.ThreadLocalRandom;

/** Per-utterance clock. Only event codes and elapsed milliseconds leave this object. */
final class TurnTiming {
    private final long id=ThreadLocalRandom.current().nextLong(1,Long.MAX_VALUE);
    private final long start=SystemClock.elapsedRealtime();
    long id(){return id;}
    void mark(DiagnosticJournal.Event event){markAt(event,SystemClock.elapsedRealtime());}
    void markAt(DiagnosticJournal.Event event,long stamp){DiagnosticLog.event(event,Math.max(0,stamp-start),id);}
    void duration(DiagnosticJournal.Event event,long value){DiagnosticLog.event(event,value,id);}
    void intent(int kind){mark(DiagnosticJournal.Event.TURN_INTENT_MS);DiagnosticLog.event(DiagnosticJournal.Event.TURN_INTENT,kind,id);}
    void route(int tier){mark(DiagnosticJournal.Event.TURN_ROUTE_MS);DiagnosticLog.event(DiagnosticJournal.Event.TURN_ROUTE,tier,id);}
}
