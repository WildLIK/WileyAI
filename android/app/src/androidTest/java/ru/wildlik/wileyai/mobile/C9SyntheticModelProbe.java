package ru.wildlik.wileyai.mobile;
import android.content.Context;
import java.util.*;
import java.util.function.Consumer;

/** Synthetic labels only; no accessibility access, user history, or configuration changes. */
final class C9SyntheticModelProbe {
    static void run(Context context)throws Exception {
        Map<String,Object> snapshot=Map.of("elements",List.of(Map.of("text","Звёздная карта","description","","role","button"),Map.of("text","Лесная тропа","description","","role","button")),"tree_quality","partial");
        try(LocalProvider local=new LocalProvider(context)){
            final String[] raw={""};
            BrainProvider probe=new BrainProvider(){public Kind kind(){return Kind.LOCAL;}public boolean nativeTools(){return false;}
                public Completion complete(List<Map<String,Object>> m,List<AndroidTools.Tool> t,boolean p,Cancellation c,Consumer<String> s)throws Exception {Completion v=local.complete(m,t,p,c,s);raw[0]=v.text();return v;}};
            ScreenModelGate.Decision found=ScreenModelGate.decide(probe,"Найди кнопку звёздная карта",ScreenRequest.Kind.FIND,snapshot,new BrainProvider.Cancellation());
            if(!found.accepted()||!found.label().equals("Звёздная карта"))throw new AssertionError("Synthetic find output: "+raw[0]);
            ScreenModelGate.Decision observed=ScreenModelGate.decide(probe,"Что сейчас открыто?",ScreenRequest.Kind.OBSERVE,snapshot,new BrainProvider.Cancellation());
            if(!observed.accepted())throw new AssertionError("Synthetic observe output: "+raw[0]);
        }
    }
    private C9SyntheticModelProbe(){}
}
