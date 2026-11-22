package ru.wildlik.wileyai.mobile;
import java.util.*;
import java.util.function.Consumer;
public final class ScreenModelGateProbe {
 static void check(boolean x){if(!x)throw new AssertionError();}
 static class Fake implements BrainProvider {
  Kind kind=Kind.LOCAL;String answer;List<Map<String,Object>> messages;List<AndroidTools.Tool> tools;int calls;
  Fake(String a){answer=a;}
  public Kind kind(){return kind;}public boolean nativeTools(){return false;}
  public Completion complete(List<Map<String,Object>> m,List<AndroidTools.Tool> t,boolean planning,Cancellation c,Consumer<String> s){check(planning);messages=m;tools=t;calls++;return new Completion(answer,List.of());}
 }
 static Map<String,Object> snapshot(){return Map.of("elements",List.of(Map.of("text","Звёздная карта","description","","role","button"),Map.of("text","Лесная тропа","description","","role","button")),"tree_quality","partial");}
 public static void main(String[] x)throws Exception{
  String found="{\"steps\":[{\"tool\":\"screen_find\",\"arguments\":{\"query\":\"Звёздная карта\"}}],\"reply\":\"\"}";
  Fake f=new Fake(found);var result=ScreenModelGate.decide(f,"Найди карту",ScreenRequest.Kind.FIND,snapshot(),new BrainProvider.Cancellation());
  check(result.accepted()&&result.label().equals("Звёздная карта"));check(f.calls==1&&f.tools.size()==1&&f.tools.get(0).name().equals("screen_find"));check(f.messages.toString().contains("Звёздная карта"));
  f=new Fake(found.replace("Звёздная карта","Несуществующая"));check(!ScreenModelGate.decide(f,"Найди",ScreenRequest.Kind.FIND,snapshot(),new BrainProvider.Cancellation()).accepted());
  f=new Fake("{\"steps\":[{\"tool\":\"open_app\",\"arguments\":{\"app_name\":\"x\"}}],\"reply\":\"\"}");boolean rejected=false;try{ScreenModelGate.decide(f,"найди",ScreenRequest.Kind.FIND,snapshot(),new BrainProvider.Cancellation());}catch(Exception expected){rejected=true;}check(rejected);
  f=new Fake(found);f.kind=BrainProvider.Kind.DIRECT_CLOUD;rejected=false;try{ScreenModelGate.decide(f,"найди",ScreenRequest.Kind.FIND,snapshot(),new BrainProvider.Cancellation());}catch(Exception expected){rejected=true;}check(rejected&&f.calls==0);
  f=new Fake(found);var c=new BrainProvider.Cancellation();c.cancel();rejected=false;try{ScreenModelGate.decide(f,"найди",ScreenRequest.Kind.FIND,snapshot(),c);}catch(Exception expected){rejected=true;}check(rejected&&f.calls==0);
  System.out.println("Local model gate fake-provider checks passed");
 }
}
