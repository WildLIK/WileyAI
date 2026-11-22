package ru.wildlik.wileyai.mobile;
import java.util.*;
public final class MemoryRetrieverProbe {
 public static void main(String[] args){
  var items=List.of(new MemoryRetriever.Candidate("Пишу фантастическую книгу",false,"other"),new MemoryRetriever.Candidate("Предпочитаю KION Музыку",true,"other"),new MemoryRetriever.Candidate("Любимый напиток чай",false,"other"));
  check(MemoryRetriever.select("Что ты помнишь о моей книге?",items,3,600).get(0).text().contains("книгу"));
  check(MemoryRetriever.select("Какой музыкальный сервис я предпочитаю?",items,3,600).get(0).text().contains("KION"));
  check(MemoryRetriever.select("Какая погода?",items,3,600).isEmpty());
  check(MemoryRetriever.select("KION",List.of(items.get(1),items.get(1)),3,600).size()==1);
  for(int size:new int[]{10,100,500}){var data=new ArrayList<MemoryRetriever.Candidate>();for(int i=0;i<size;i++)data.add(items.get(i%3));long start=System.nanoTime();for(int i=0;i<100;i++)MemoryRetriever.select("моя книга",data,3,600);System.out.println(size+" records, 100 runs ms="+(System.nanoTime()-start)/1000000);}
 }
 static void check(boolean value){if(!value)throw new AssertionError();}
}
