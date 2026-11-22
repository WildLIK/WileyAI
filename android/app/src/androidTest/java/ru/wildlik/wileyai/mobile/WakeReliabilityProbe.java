package ru.wildlik.wileyai.mobile;

import android.app.Instrumentation;
import android.content.Context;
import java.nio.file.Files;
import java.util.List;
import org.json.JSONObject;

/** Real Android parser and local clock, isolated journal, no mutating phone actions. */
final class WakeReliabilityProbe {
    static String run(Instrumentation runner,Context context)throws Exception{
        int checked=0;
        for(String prefix:List.of("","Вайли, ","Уайли ","Вай ли ","Уай ли, ","Окей, Уай ли — ")){
            for(String question:List.of("сколько времени?","сколько сейчас времени","который час?")){
                PhoneCommands.Action time=PhoneCommands.parse(prefix+question,true);
                require(time!=null&&time.kind.equals("info")&&time.value.equals("time"));
                checked++;
            }
        }
        require(PhoneCommands.parse("Уайли, сделай потише",true).value.equals("down"));
        require(PhoneCommands.parse("Вайли, включи музыку",true).kind.equals("media"));
        require(PhoneCommands.parse("Вайли, открой Telegram",true).value.equals("Telegram"));
        require(PhoneCommands.blockedVoice("Уай ли не открывай браузер")==1);
        require(PhoneCommands.blockedVoice("Вайли открой приложение")==2);
        require(PhoneCommands.parse("Уайли открой приложение",true)==null);
        require(PhoneCommands.blockedVoice("Почему не открывается браузер?")==0);
        String[] response={""};
        runner.runOnMainSync(()->PhoneActionCore.execute(context,PhoneCommands.parse("Уай ли — который час?",true),text->response[0]=text));
        require(response[0].contains("по времени телефона"));

        WakeActivation.Gate gate=new WakeActivation.Gate();
        WakeActivation prior=new WakeActivation(101,100,1,false,920,880);
        WakeActivation next=new WakeActivation(102,200,2,false,990,850);
        require(gate.reserve(prior)&&!gate.reserve(next)&&!gate.matches(next.id()));
        require(gate.take()==prior&&!gate.waiting()&&gate.reserve(next)&&!gate.matches(prior.id())&&gate.take()==next);

        var directory=Files.createTempDirectory(context.getCacheDir().toPath(),"wake-probe-");
        var journal=new DiagnosticJournal(directory.resolve("events.txt"));
        long now=System.currentTimeMillis();
        try{
            journal.append(now,10,DiagnosticJournal.Event.VOICE_WAKE,0,101);
            journal.append(now,10,DiagnosticJournal.Event.WAKE_CANDIDATE_FINAL,1,102);
            journal.append(now,10,DiagnosticJournal.Event.VOICE_WINDOW_SHOW,0);
            require(journal.markLastWakeFalse(now,10)==1);
            require(journal.markLastWakeFalse(now,11)==2);
            require(journal.read(now).stream().filter(row->row.contains("|WAKE_FALSE_MARK|1|101")).count()==1);
            return new JSONObject().put("direct_time_forms",checked).put("real_clock",true)
                .put("false_label_deduplicated",true).put("stale_window_blocked",true)
                .put("real_mutations",0).toString();
        }finally{journal.clear();Files.deleteIfExists(directory);}
    }
    private static void require(boolean condition){if(!condition)throw new AssertionError("Wake reliability regression");}
}
