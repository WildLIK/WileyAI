package ru.wildlik.wileyai.mobile;
import java.util.*;
/** A bounded, single-use app selection; it never launches anything. */
final class AppSelection {
 private List<AppRegistry.App> candidates=List.of();private long expires;private static final long TTL=120000;
 private String phrase="";
 void offer(List<AppRegistry.App> apps,long now){offer(apps,now,"");}
 void offer(List<AppRegistry.App> apps,long now,String name){candidates=List.copyOf(apps);expires=now+TTL;phrase=name;}
 String phrase(long now){return active(now)?phrase:"";}
 void clear(){candidates=List.of();expires=0;phrase="";}
 boolean active(long now){if(now>=expires)clear();return !candidates.isEmpty();}
 List<AppRegistry.App> list(long now){return active(now)?candidates:List.of();}
 int select(String input,long now){if(!active(now))return -3;String s=input.toLowerCase(Locale.ROOT).replace('ё','е').replaceAll("[.!?,]", " ").trim().replaceAll("\\s+"," ");
  if(s.matches("нет|не надо|отмена|отмени|передумал"))return -2;
  if(s.matches("да|ага|конечно|открывай|запускай|подтверждаю"))return candidates.size()==1?0:-1;
  String[] words={"(?:перв(?:ый|ое|ую)|один|одна|1)","(?:втор(?:ой|ое|ую)|два|две|2)","(?:трет(?:ий|ье|ью)|три|3)","(?:четверт(?:ый|ое|ую)|четыре|4)","(?:пят(?:ый|ое|ую)|пять|5)"};
  if(s.matches("(?:открой |выбираю |выбери )?(?:самое )?последн(?:ее|ий|юю)(?: приложение| вариант)?"))return candidates.size()-1;
  for(int i=0;i<words.length;i++)if(s.matches("(?:открой |выбираю |выбери )?(?:номер |вариант )?"+words[i]+"(?: вариант| приложение)?"))return i<candidates.size()?i:-1;
  List<AppRegistry.App> found=AppRegistry.resolve(candidates,s);return found.size()==1?candidates.indexOf(found.get(0)):-1;
 }
}
