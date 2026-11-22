package ru.wildlik.wileyai.mobile;

import java.util.List;
import java.util.Locale;
import java.util.UUID;

/** Metadata for the isolated, explicitly recorded research set. */
final class WakeStudy {
    static final List<String> SPLITS=List.of("development","validation","test");
    static final List<String> LABELS=List.of(
        "Вайли","Уайли","Окей, Вайли","Окей, Уайли",
        "Вайли, сколько времени?","Уайли, сколько времени?",
        "Обычная речь без обращения","Созвучные слова без обращения","Шум или неречевой звук");
    static final List<String> ROLES=List.of("unknown","owner","other");
    static final List<String> ROLE_LABELS=List.of("Неизвестно","Владелец","Другой человек");
    static final List<String> CONTENT_LABELS=List.of("Настоящее обращение к WileyAI",
        "Созвучная фраза без обращения","Обычная речь без обращения","Шум или неречевой звук");
    static final List<String> ENVIRONMENTS=List.of("quiet","room","reverberant","outdoor","background");
    static final List<String> LEVELS=List.of("normal","quiet");
    static final List<Integer> DISTANCES=List.of(30,100,200,400);
    static final int MAX_SECONDS=120;
    static final int MAX_CLIPS=100;
    static final int MIN_SAMPLES=8000;
    static final String HEADER="id,speaker_id,session_id,split,kind,file,phrase,voice_level,distance_m,environment,wake_start_s,wake_end_s,vosk_status,started_at_ms,samples";
    static final String EXPORT_HEADER=HEADER+",speaker_role,speech_kind,session_title";

    record Session(String id,String speaker,String split,String level,int distanceCm,String environment,long started) {
        Session {
            if(!WakeSampleStore.validId(id)||!speaker.equals(alias(speaker))||!SPLITS.contains(split)||
                !LEVELS.contains(level)||!DISTANCES.contains(distanceCm)||!ENVIRONMENTS.contains(environment)||started<=0)
                throw new IllegalArgumentException("Invalid study session");
        }
    }
    static String alias(String entered){
        String clean=entered.trim().toLowerCase(Locale.ROOT);
        if(!clean.matches("[a-z0-9][a-z0-9_-]{1,23}"))throw new IllegalArgumentException("Invalid speaker alias");
        return clean;
    }
    static Session session(String entered,String split,String level,int distance,String environment,long started){
        return new Session(UUID.randomUUID().toString(),alias(entered),split,level,distance,environment,started);
    }
    static boolean negative(int label){return label>=6;}
    static String kind(int label){LABELS.get(label);return negative(label)?"negative":"positive";}
    static String content(int label){
        LABELS.get(label);
        return switch(label){case 6->"ordinary";case 7->"confusable";case 8->"noise";default->"wake";};
    }
    static int categoryLabel(int category){return switch(category){case 1->7;case 2->6;case 3->8;default->throw new IllegalArgumentException();};}
    static int limitSeconds(int label){return negative(label)?MAX_SECONDS:4;}
    static String row(String id,Session session,int label,String result,int samples){
        if(!WakeSampleStore.validId(id)||samples<MIN_SAMPLES||samples>16_000*MAX_SECONDS
            ||!List.of("accepted","not_detected","unavailable").contains(result))
            throw new IllegalArgumentException("Invalid study sample");
        // Selected labels may contain a comma. Quote every column for compatible import.
        return List.of(id,session.speaker,session.id,session.split,kind(label),id+".wav",LABELS.get(label),
            session.level,Double.toString(session.distanceCm/100.0),session.environment,"","",
            result,Long.toString(session.started),Integer.toString(samples)).stream()
            .map(WakeStudy::quote).collect(java.util.stream.Collectors.joining(","));
    }
    static String quote(String value){return "\""+value.replace("\"","\"\"")+"\"";}
    private WakeStudy() {}
}
