package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.util.*;

/** Pure protocol parsing. Partial text, guessed tool names and missing completion cannot execute. */
final class ResponsesWire {
    private static final class Terminal extends RuntimeException {}
    private static String string(Map<?,?> item,String key){Object value=item.get(key);if(!(value instanceof String text))throw new IllegalArgumentException("Изменился формат ответа OpenAI");return text;}
    static BrainProvider.Completion read(Reader reader,boolean toolsAllowed,Runnable check)throws IOException{
        StringBuilder answer=new StringBuilder();List<BrainProvider.Call> calls=new ArrayList<>();List<Map<String,Object>> continuation=new ArrayList<>();Set<String> ids=new HashSet<>();
        try{ProviderSse.read(reader,raw->{
            check.run();Object parsed=StrictJson.parse(raw);if(!(parsed instanceof Map<?,?> event))throw new IllegalArgumentException("Изменился формат ответа OpenAI");String type=string(event,"type");
            if(type.equals("response.output_text.delta")){answer.append(string(event,"delta"));if(answer.length()>16384)throw new IllegalArgumentException("Ответ планировщика слишком большой");}
            else if(type.equals("response.output_item.done")){
                if(!(event.get("item") instanceof Map<?,?> item))throw new IllegalArgumentException("Изменился формат ответа OpenAI");String kind=string(item,"type");
                if(kind.equals("function_call")){
                    String name=string(item,"name"),namespace=item.containsKey("namespace")?string(item,"namespace"):"";
                    if(name.startsWith("wiley_android."))name=name.substring(14);
                    if(!toolsAllowed||!namespace.isEmpty()&&!namespace.equals("wiley_android")||calls.size()>=4)throw new IllegalArgumentException("Неожиданный инструмент OpenAI");
                    String id=string(item,"call_id");if(!id.matches("[A-Za-z0-9_-]{1,160}")||!ids.add(id))throw new IllegalArgumentException("Некорректный ID инструмента");
                    calls.add(new BrainProvider.Call(id,name,string(item,"arguments")));
                }
                if(Set.of("reasoning","message","function_call").contains(kind)){
                    if(continuation.size()>=30)throw new IllegalArgumentException("Ответ планировщика слишком большой");Map<String,Object> value=new LinkedHashMap<>();for(var entry:item.entrySet())value.put((String)entry.getKey(),entry.getValue());continuation.add(value);
                }
            }
            else if(type.equals("response.completed")){if(!(event.get("response") instanceof Map<?,?> response)||!"completed".equals(response.get("status")))throw new IllegalArgumentException("OpenAI не подтвердил завершение ответа");throw new Terminal();}
            else if(Set.of("response.failed","response.incomplete","error").contains(type))throw new IllegalArgumentException("OpenAI не завершил ответ. Проверьте лимиты аккаунта и доступ модели. План не выполнялся.");
        });}catch(Terminal done){check.run();return new BrainProvider.Completion(answer.toString(),List.copyOf(calls),List.copyOf(continuation));}
        throw new IOException("Поток OpenAI оборвался до подтверждения завершения. План не выполнялся.");
    }
    private ResponsesWire(){}
}
