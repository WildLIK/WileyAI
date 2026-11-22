package ru.wildlik.wileyai.mobile;

import android.content.Context;
import java.io.File;
import java.nio.file.Files;
import java.util.UUID;
import org.json.JSONObject;

/** Exercises legacy discovery and persistence in an isolated instrumented directory. */
final class WakeStudySessionsProbe {
    static void run(Context context) throws Exception {
        File folder=Files.createTempDirectory(context.getCacheDir().toPath(),"study-probe-").toFile();
        String id=UUID.randomUUID().toString();
        var prior=WakeStudy.session("prior","test","quiet",100,"room",1000);
        File sidecar=new File(folder,id+".json");
        File waveform=new File(folder,id+".wav");
        try {
            byte[] old=new JSONObject().put("id",id).put("session_id",prior.id()).put("speaker_id",prior.speaker())
                .put("split",prior.split()).put("voice_level",prior.level()).put("distance_cm",prior.distanceCm())
                .put("environment",prior.environment()).put("started_at_ms",prior.started()).put("recorded_at_ms",1500)
                .put("label",6).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            Files.write(sidecar.toPath(),old);
            Files.write(waveform.toPath(),new byte[44]);
            var first=new WakeStudySessions(folder,new File[]{sidecar});
            var legacy=first.get(prior.id());
            check(legacy.count==1&&legacy.lastRecorded==1500&&legacy.role.equals("unknown"));
            first.select(legacy);
            first.preferences(legacy,"Resume test","owner",8);
            var reopened=new WakeStudySessions(folder,new File[]{sidecar});
            var entry=reopened.get(reopened.selected);
            check(entry.session.id().equals(prior.id())&&entry.count==1&&entry.title.equals("Resume test"));
            check(entry.role.equals("owner")&&entry.label==8);
            var next=WakeStudy.session("guest","validation","normal",30,"room",2000);
            var guest=reopened.openOrCreate(next);
            var repeated=reopened.openOrCreate(WakeStudy.session("guest","validation","normal",30,"room",2100));
            check(guest.session.id().equals(repeated.session.id())&&reopened.list().size()==2);
            check(java.util.Arrays.equals(Files.readAllBytes(sidecar.toPath()),old));
            check(WakeStudy.kind(8).equals("negative")&&WakeStudy.content(8).equals("noise"));
        } finally {
            for(File file:folder.listFiles())Files.delete(file.toPath());
            Files.delete(folder.toPath());
        }
    }
    private static void check(boolean valid){if(!valid)throw new AssertionError("Study session invariant");}
}
