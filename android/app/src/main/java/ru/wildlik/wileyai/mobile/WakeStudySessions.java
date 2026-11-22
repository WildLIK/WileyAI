package ru.wildlik.wileyai.mobile;

import android.util.AtomicFile;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONArray;
import org.json.JSONObject;

/** Session index in the existing study directory. Legacy sessions are recovered from sample sidecars. */
final class WakeStudySessions {
    static final class Entry {
        final WakeStudy.Session session;
        String title="", role="unknown";
        int label, count;
        long lastRecorded;
        Entry(WakeStudy.Session value) { session=value; }
        String displayName() { return title.isBlank()?session.speaker():title; }
    }
    private final File directory;
    private final AtomicFile journal;
    private final Map<String,Entry> entries=new LinkedHashMap<>();
    private boolean writable=true;
    String selected="";

    WakeStudySessions(File directory, File[] sidecars) {
        this.directory=directory;
        journal=new AtomicFile(new File(directory,"sessions.json"));
        try {
            JSONObject data=new JSONObject(new String(journal.readFully(),StandardCharsets.UTF_8));
            JSONArray items=data.getJSONArray("sessions");
            for(int i=0;i<items.length();i++){
                JSONObject item=items.getJSONObject(i);
                Entry entry=new Entry(fields(item));
                entry.title=item.optString("title");
                entry.role=validatedRole(item.optString("role"));
                entry.label=validLabel(item.optInt("label"));
                entries.put(entry.session.id(),entry);
            }
            selected=data.optString("selected");
        }catch(FileNotFoundException missing){
            // Existing exports only have sample sidecars.
        }catch(Exception damaged){writable=false;}
        recount(sidecars);
    }
    static WakeStudy.Session fields(JSONObject row) throws org.json.JSONException {
        return new WakeStudy.Session(row.getString("session_id"),row.getString("speaker_id"),row.getString("split"),
            row.getString("voice_level"),row.getInt("distance_cm"),row.getString("environment"),row.getLong("started_at_ms"));
    }
    static String validatedRole(String role){return WakeStudy.ROLES.contains(role)?role:"unknown";}
    private static int validLabel(int label){return label>=0&&label<WakeStudy.LABELS.size()?label:0;}

    void recount(File[] sidecars) {
        for(Entry entry:entries.values()){entry.count=0;entry.lastRecorded=0;}
        for(File file:sidecars){
            try{
                if(file.length()>8192)continue;
                JSONObject row=new JSONObject(new String(java.nio.file.Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
                String id=row.getString("id");
                if(!WakeSampleStore.validId(id)||!file.getName().equals(id+".json")||
                    !new File(directory,id+".wav").isFile())continue;
                WakeStudy.Session session=fields(row);
                Entry entry=entries.computeIfAbsent(session.id(),ignored->new Entry(session));
                if (!entry.session.equals(session)) continue;
                entry.count++;
                long at=row.optLong("recorded_at_ms",session.started());
                if(at>=entry.lastRecorded)entry.lastRecorded=at;
            }catch(Exception invalid){/* Keep malformed samples untouched. */}
        }
    }
    Entry get(String id){return entries.get(id);}
    List<Entry> list(){
        return entries.values().stream()
            .sorted(Comparator.comparingLong((Entry entry)->Math.max(entry.lastRecorded,entry.session.started())).reversed())
            .collect(java.util.stream.Collectors.toList());
    }
    Entry openOrCreate(WakeStudy.Session proposed) throws IOException {
        for(Entry entry:entries.values()){
            var s=entry.session;
            if(s.speaker().equals(proposed.speaker())&&!s.split().equals(proposed.split()))
                throw new IllegalArgumentException("speaker split");
        }
        Entry existing=list().stream().filter(entry->entry.count==0&&sameSetup(entry.session,proposed)).findFirst().orElse(null);
        if (existing!=null){select(existing);return existing;}
        Entry newEntry=new Entry(proposed);
        String before=selected;
        entries.put(proposed.id(),newEntry);
        selected=proposed.id();
        try{save();}catch(IOException failure){entries.remove(proposed.id());selected=before;throw failure;}
        return newEntry;
    }
    void select(Entry entry)throws IOException{
        String before=selected;selected=entry.session.id();
        try{save();}catch(IOException failure){selected=before;throw failure;}
    }
    void preferences(Entry entry,String title,String role,int label)throws IOException{
        String oldTitle=entry.title,oldRole=entry.role;
        int oldLabel=entry.label;
        entry.title=title;entry.role=validatedRole(role);entry.label=validLabel(label);
        try{save();}catch(IOException failure){entry.title=oldTitle;entry.role=oldRole;entry.label=oldLabel;throw failure;}
    }
    private static boolean sameSetup(WakeStudy.Session a,WakeStudy.Session b){
        return a.speaker().equals(b.speaker())&&a.split().equals(b.split())&&a.level().equals(b.level())&&
            a.distanceCm()==b.distanceCm()&&a.environment().equals(b.environment());
    }
    private void save() throws IOException {
        if(!writable||(!directory.isDirectory()&&!directory.mkdirs()))throw new IOException("Study index unavailable");
        FileOutputStream stream=null;
        try{
            JSONArray all=new JSONArray();
            for(Entry entry:entries.values()){
                var s=entry.session;
                all.put(new JSONObject().put("session_id",s.id()).put("speaker_id",s.speaker()).put("split",s.split())
                    .put("voice_level",s.level()).put("distance_cm",s.distanceCm()).put("environment",s.environment())
                    .put("started_at_ms",s.started()).put("title",entry.title).put("role",entry.role).put("label",entry.label));
            }
            byte[] data=new JSONObject().put("selected",selected).put("sessions",all).toString().getBytes(StandardCharsets.UTF_8);
            stream=journal.startWrite();
            stream.write(data);
            journal.finishWrite(stream);
        }catch(Exception failure){
            if(stream!=null)journal.failWrite(stream);
            throw new IOException("Study index write failed",failure);
        }
    }
}
