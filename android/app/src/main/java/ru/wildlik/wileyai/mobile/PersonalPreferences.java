package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** User-entered preferences and explicitly saved memories, separate from chat history. */
final class PersonalPreferences {
    private static final Object MEMORY_LOCK=new Object();
    private final SharedPreferences prefs;
    record Memory(String id,String text) {}

    PersonalPreferences(Context context) {
        prefs=context.getSharedPreferences("wiley-personal",Context.MODE_PRIVATE);
    }

    String name(){return prefs.getString("name","");}
    String address(){return prefs.getString("address","");}
    String preferences(){return prefs.getString("preferences","");}
    String instructions(){return prefs.getString("instructions","");}
    boolean instructionsEnabled(){return prefs.getBoolean("instructions_enabled",true);}
    boolean memoryEnabled(){return prefs.getBoolean("memory_enabled",false);}
    void memoryEnabled(boolean enabled){prefs.edit().putBoolean("memory_enabled",enabled).apply();}
    void profile(String name,String address,String preferences){
        prefs.edit().putString("name",bounded(name,80)).putString("address",bounded(address,80)).putString("preferences",bounded(preferences,350)).apply();
    }
    void communication(String instructions,boolean enabled){
        prefs.edit().putString("instructions",bounded(instructions,600)).putBoolean("instructions_enabled",enabled).apply();
    }

    List<Memory> memories(){
        List<Memory> result=new ArrayList<>();
        try {
            JSONArray records=new JSONArray(prefs.getString("confirmed_memories","[]"));
            for(int i=0;i<records.length();i++){
                JSONObject entry=records.getJSONObject(i);
                result.add(new Memory(entry.getString("id"),entry.getString("text")));
            }
        } catch(org.json.JSONException invalid){throw new IllegalStateException("Не удалось прочитать память",invalid);}
        return result;
    }

    void saveMemory(String id,String text){
        synchronized(MEMORY_LOCK){
        String clean=bounded(text,400);
        if(clean.isEmpty())return;
        List<Memory> entries=memories();
        if(id==null){
            if(entries.size()>=100)throw new IllegalStateException("Можно хранить до 100 воспоминаний");
            entries.add(new Memory(UUID.randomUUID().toString(),clean));
        }else{
            entries.replaceAll(entry->entry.id().equals(id)?new Memory(id,clean):entry);
        }
        write(entries);
        }
    }

    void removeMemory(String id){
        synchronized(MEMORY_LOCK){
        List<Memory> entries=memories();
        if(!entries.removeIf(entry->entry.id().equals(id)))throw new IllegalStateException("Воспоминание уже удалено");
        write(entries);
        }
    }

    private void write(List<Memory> entries){
        JSONArray records=new JSONArray();
        for(Memory entry:entries){
            try{records.put(new JSONObject().put("id",entry.id()).put("text",entry.text()));}
            catch(org.json.JSONException invalid){throw new IllegalStateException(invalid);}
        }
        if(!prefs.edit().putString("confirmed_memories",records.toString()).commit())throw new IllegalStateException("Не удалось сохранить память");
    }

    String localResponseContext(){return localResponseContext("");}
    private String responseContext(String request){
        StringBuilder result=new StringBuilder();
        append(result,"Имя пользователя",name());
        append(result,"Предпочтительное обращение, когда уместно",address());
        append(result,"Пользовательские предпочтения",preferences());
        if(instructionsEnabled())append(result,"Пожелания о стиле ответа",instructions());
        if(memoryEnabled()){
            List<Memory> entries;
            try{entries=memories();}
            catch(IllegalStateException invalid){entries=List.of();}
            List<MemoryRetriever.Candidate> candidates=new ArrayList<>();
            for(Memory entry:entries)candidates.add(new MemoryRetriever.Candidate(bounded(entry.text(),200),false,"other"));
            for(var match:MemoryRetriever.select(request,candidates,3,600))append(result,"Подтверждённый факт, используй только по теме",match.text());
        }
        if(result.length()==0)return "";
        return ("\nУчитывай эти пожелания только при написании ответа и если они совместимы с основными инструкциями."+result).replace("<|","< | ");
    }

    String localResponseContext(String request){
        String context=responseContext(request);
        return context+ProfileIdentity.context(name(),address());
    }

    private static void append(StringBuilder out,String title,String value){
        if(!value.isEmpty())out.append('\n').append(title).append(": ").append(value);
    }
    private static String bounded(String text,int max){
        String clean=text.trim();
        return clean.substring(0,Math.min(max,clean.length()));
    }
}
