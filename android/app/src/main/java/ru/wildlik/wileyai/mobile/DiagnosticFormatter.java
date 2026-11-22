package ru.wildlik.wileyai.mobile;
import java.time.Instant;
import java.util.*;
/** Formats only records previously admitted by the journal schema. */
final class DiagnosticFormatter {
 static String events(List<String> lines){
  StringBuilder out=new StringBuilder("\nХронология (UTC | ID сессии | событие | значение | ID реплики, если есть)\n");
  EnumMap<DiagnosticJournal.Event,Integer> counts=new EnumMap<>(DiagnosticJournal.Event.class);
  for(String line:lines){String[] v=line.split("\\|",-1);if(v.length!=4&&v.length!=5)continue;try{
   long ts=Long.parseLong(v[0]),session=Long.parseLong(v[1]),value=Long.parseLong(v[3]);
   long turn=v.length==5?Long.parseLong(v[4]):0;
   DiagnosticJournal.Event event=DiagnosticJournal.Event.valueOf(v[2]);counts.put(event,counts.getOrDefault(event,0)+1);
   out.append(Instant.ofEpochMilli(ts)).append(" | ").append(session).append(" | ").append(event.name()).append(" | ").append(value);
   if(turn>0)out.append(" | ").append(turn);
   out.append('\n');
  }catch(Exception ignored){}}
  out.append("\nИтого событий по типам:\n");for(var item:counts.entrySet())out.append(item.getKey()).append(": ").append(item.getValue()).append('\n');return out.toString();
 }
 private DiagnosticFormatter(){}
}
