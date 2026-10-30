import ru.wildlik.wileyai.mobile.GatewayWire;
import java.io.*;
import java.util.*;
import java.util.regex.*;

/** Exercises the exact Android transport against a real loopback Gateway. */
public class GatewayWireProbe {
    static String id(String json){Matcher match=Pattern.compile("\"id\"\\s*:\\s*\"([a-f0-9]{32})\"").matcher(json);if(!match.find())throw new AssertionError(json);return match.group(1);}
    static String ok(GatewayWire.Reply reply){if(reply.status()!=200)throw new AssertionError(reply.body());return reply.body();}
    static void check(boolean condition){if(!condition)throw new AssertionError();}
    static void parser()throws Exception{
        List<GatewayWire.Event> received=new ArrayList<>();
        String data=": heartbeat\r\nid: 1\nevent: message.delta\ndata: {\"text\":\"a\"}\n\nid: 1\nevent: message.delta\ndata: duplicate\n\nid: 2\nevent: run.completed\ndata: {}\n\n";
        check(GatewayWire.readEvents(new StringReader(data),0,received::add)==2&&received.size()==2);
        check(GatewayWire.readEvents(new StringReader("id: 3\ndata: partial"),2,received::add)==2);
        try{GatewayWire.readEvents(new StringReader("data: missing-id\n\n"),0,e->{});throw new AssertionError();}catch(IOException expected){}
        try{GatewayWire.readEvents(new StringReader("data: "+"x".repeat(256*1024)+"\n\n"),0,e->{});throw new AssertionError();}catch(IOException expected){}
        for(String url:List.of("http://example.com","https://a.example/path","https://user@a.example","https://a.example?token=x")){try{new GatewayWire(url,"a".repeat(40));throw new AssertionError();}catch(IOException expected){}}
    }
    public static void main(String[] args)throws Exception{
        parser();
        if(args.length==0){System.out.println("PARSER_OK");return;}
        GatewayWire wire=new GatewayWire(args[0],System.getenv("WILEY_GATEWAY_TEST_TOKEN"),true);
        check(ok(wire.request("GET","/api/v1/info",null)).contains("\"protocol\":1"));
        String account=id(ok(wire.request("POST","/api/v1/connections","{\"provider_id\":\"test-provider\",\"consent\":true}")));
        check(ok(wire.request("GET","/api/v1/connections/"+account+"/models",null)).contains("test-text-v1"));
        String conversation=id(ok(wire.request("POST","/api/v1/conversations","{\"connection_id\":\""+account+"\",\"model_id\":\"test-text-v1\"}")));
        String body="{\"request_id\":\""+UUID.randomUUID().toString().replace("-","")+"\",\"text\":\"Java transport request\"}";
        String run=id(ok(wire.request("POST","/api/v1/conversations/"+conversation+"/runs",body)));
        List<GatewayWire.Event> received=new ArrayList<>();long cursor=wire.events(run,0,received::add);
        check(cursor>2&&received.get(received.size()-1).type().equals("run.completed"));
        check(received.stream().anyMatch(e->e.type().equals("message.delta")));
        check(id(ok(wire.request("POST","/api/v1/conversations/"+conversation+"/runs",body))).equals(run));
        List<GatewayWire.Event> replay=new ArrayList<>();wire.events(run,cursor-1,replay::add);check(replay.size()==1&&replay.get(0).id()==cursor);
        check(ok(wire.request("GET","/api/v1/conversations/"+conversation,null)).contains("Java transport request"));
        System.out.println("NETWORK_SSE_HISTORY_REPLAY_OK");
    }
}
