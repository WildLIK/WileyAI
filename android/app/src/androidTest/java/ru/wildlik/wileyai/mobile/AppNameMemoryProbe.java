package ru.wildlik.wileyai.mobile;
import android.content.Context;
import android.content.SharedPreferences;
import java.util.*;
/** Synthetic, isolated preferences only; no launcher or user app state touched. */
final class AppNameMemoryProbe {
 static void run(Context ctx){SharedPreferences prefs=ctx.getSharedPreferences("test-app-name-memory-isolated",0);prefs.edit().clear().commit();try{
 AppRegistry.App a=new AppRegistry.App("fake.pkg/.Main","Test One","fake.pkg",".Main",List.of()),b=new AppRegistry.App("fake2/.Main","Test Two","fake2",".Main",List.of());
 AppNameMemory one=new AppNameMemory(prefs);if(!one.record("тест имя",a,"test"))throw new AssertionError("save");
 AppNameMemory reopened=new AppNameMemory(prefs);if(!reopened.resolve("тест имя",List.of(a)).equals(List.of(a)))throw new AssertionError("reload");
 if(reopened.record("тест имя",b,"test"))throw new AssertionError("conflict");if(!reopened.resolve("тест имя",List.of(b)).isEmpty())throw new AssertionError("removed app");
 if(!reopened.rename("тест имя","новое имя")||!reopened.resolve("новое имя",List.of(a)).equals(List.of(a)))throw new AssertionError("rename");
 reopened.remove("новое имя");if(!reopened.entries().isEmpty())throw new AssertionError("remove");
 }finally{prefs.edit().clear().commit();}}
 private AppNameMemoryProbe(){}
}
