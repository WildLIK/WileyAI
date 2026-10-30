package ru.wildlik.wileyai.mobile;

import org.json.*;
import java.util.*;
import java.util.function.Consumer;

/** Optional server-backed planner. Uses separate jobs; never stores JSON plans as phone chat replies. */
final class RemoteGatewayProvider implements BrainProvider {
    private final JSONObject profile;
    RemoteGatewayProvider(JSONObject profile){this.profile=profile;}
    public Kind kind(){return Kind.REMOTE_GATEWAY;}public boolean nativeTools(){return false;}
    public Completion complete(List<Map<String,Object>> messages,List<AndroidTools.Tool> tools,boolean planning,Cancellation cancel,Consumer<String> status)throws Exception{
        GatewayWire wire=new GatewayWire(profile.getString("url"),profile.getString("token"));String request=UUID.randomUUID().toString().replace("-","");cancel.onCancel(()->{wire.cancel();});
        JSONObject conversation=GatewayClient.json(wire.request("POST","/api/v1/conversations",new JSONObject().put("connection_id",profile.getString("connection_id")).put("model_id",profile.getString("model_id")).toString()));
        String id=conversation.getString("id");StringBuilder text=new StringBuilder();boolean[] completed={false};String[] problem={null};
        try{cancel.check();JSONObject run=GatewayClient.json(wire.request("POST","/api/v1/conversations/"+id+"/runs",new JSONObject().put("request_id",request).put("text",ToolJson.text(messages)).toString()));wire.events(run.getString("id"),0,event->{try{JSONObject data=new JSONObject(event.data());if(event.type().equals("message.delta")){text.append(data.optString("text"));if(text.length()>16384)throw new IllegalStateException("Ответ планировщика слишком большой");}else if(event.type().equals("run.completed"))completed[0]=true;else if(event.type().matches("run\\.(failed|cancelled|interrupted)"))problem[0]="Gateway прервал ответ. План не выполнялся.";}catch(JSONException error){throw new IllegalStateException("Некорректный поток Gateway");}});cancel.check();if(!completed[0])throw new Exception(problem[0]==null?"Соединение с Gateway прервалось. Действия не выполнялись.":problem[0]);return new Completion(text.toString(),List.of());}
        finally{if(cancel.cancelled())try{new GatewayWire(profile.getString("url"),profile.getString("token")).request("POST","/api/v1/requests/"+request+"/cancel","{}");}catch(Exception ignored){}}
    }
}
