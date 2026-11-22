package ru.wildlik.wileyai.mobile;
import java.util.*;
public final class AppSelectionProbe {
 static void check(boolean b){if(!b)throw new AssertionError();}
 static AppRegistry.App app(String label){return new AppRegistry.App(label,label,label,"Main",List.of());}
 public static void main(String[] x){
  AppRegistry.App a=app("Umamusume"), b=app("Wildberries"), c=app("Ozon"), d=app("Qwen"),e=app("Starfield");List<AppRegistry.App> all=List.of(a,b,c,d,e);
  check(AppRegistry.suggest(all,"вайлдберриз").contains(b));check(AppRegistry.resolve(all,"квен").contains(d));
  check(AppRegistry.resolve(all,"умамусуме").contains(a)||AppRegistry.suggest(all,"умамусуме").contains(a));
  check(AppRegistry.resolve(all,"озон").contains(c)||AppRegistry.suggest(all,"озон").contains(c));
  check(AppRegistry.suggest(all,"старфилд").contains(e));
  AppSelection p=new AppSelection();p.offer(List.of(a),100);check(p.select("да",101)==0);check(p.select("открывай",101)==0);check(p.select("не надо",101)==-2);
  p.offer(List.of(a,b),100);check(p.select("первое",101)==0);check(p.select("номер два",101)==1);check(p.select("второй вариант",101)==1);check(p.select("выбираю второе",101)==1);check(p.select("да",101)==-1);check(p.select("последнее",101)==1);check(p.select("номер 5",101)==-1);check(p.select("Wildberries",101)==1);check(!p.active(120100));check(p.select("да",120101)==-3);
  System.out.println("app selection passed");
 }
}
