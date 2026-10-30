package ru.wildlik.wileyai.mobile;

import java.io.*;

public final class ResponsesProbe {
    private static String event(String value){return "data: "+value+"\n\n";}
    public static void main(String[] args)throws Exception{
        String scenario=args[0];String text=event("{\"type\":\"response.output_text.delta\",\"delta\":\"Привет\"}"),done=event("{\"type\":\"response.completed\",\"response\":{\"status\":\"completed\"}}"),call=event("{\"type\":\"response.output_item.done\",\"item\":{\"type\":\"function_call\",\"name\":\"wiley_android.set_volume\",\"call_id\":\"call_one\",\"arguments\":\"{\\\"percent\\\":30}\"}}");
        String stream=switch(scenario){case "text"->text+done;case "native"->call+done;case "duplicate-id"->call+call+done;case "wrong-namespace"->call.replace("wiley_android.set_volume","other.set_volume").replace("\"name\":","\"namespace\":\"other\",\"name\":")+done;case "tools-off"->call+done;case "partial"->text;case "failed"->text+event("{\"type\":\"response.failed\"}");case "duplicate-json"->event("{\"type\":\"response.completed\",\"type\":\"response.completed\",\"response\":{\"status\":\"completed\"}}");case "false-completion"->done.replace("\"status\":\"completed\"","\"status\":\"incomplete\"");case "cancel"->call+done;case "bounded-comments"->(":"+"x".repeat(2000)+"\n").repeat(1100);case "terminal"->text+done+"unfinished";default->throw new AssertionError();};
        boolean accepted=false;try{
            BrainProvider.Completion result=ResponsesWire.read(new StringReader(stream),!scenario.equals("tools-off"),()->{if(scenario.equals("cancel"))throw new IllegalStateException("cancelled");});accepted=true;
            if(scenario.equals("native")){if(result.calls().size()!=1||!result.calls().get(0).id().equals("call_one")||!result.calls().get(0).name().equals("set_volume")||result.continuation().size()!=1)throw new AssertionError("native identity/continuation");}
            else if(!result.text().equals("Привет"))throw new AssertionError("text mismatch");
        }catch(IOException|IllegalArgumentException|IllegalStateException expected){}
        boolean wanted=scenario.equals("text")||scenario.equals("native")||scenario.equals("terminal");if(accepted!=wanted)throw new AssertionError("Unexpected protocol acceptance: "+scenario);
        System.out.println("RESPONSES_OK "+scenario);
    }
}
