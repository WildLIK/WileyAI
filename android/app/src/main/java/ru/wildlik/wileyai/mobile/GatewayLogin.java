package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.*;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Provider authentication uses the system browser and one bounded IPv4 loopback listener. */
final class GatewayLogin implements AutoCloseable {
    private final ExecutorService worker=Executors.newSingleThreadExecutor();private volatile ServerSocket listener;private volatile boolean closed;
    void start(Activity activity,JSONObject profile,String account,Consumer<String> done){
        Handler main=new Handler(Looper.getMainLooper());
        worker.execute(()->{
            String result="Вход не завершён. Повторите подключение.";
            try(ServerSocket socket=new ServerSocket()){
                listener=socket;socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),0));socket.setSoTimeout(300000);
                String redirect="http://127.0.0.1:"+socket.getLocalPort()+"/auth/callback";
                GatewayWire wire=new GatewayWire(profile.getString("url"),profile.getString("token"));
                JSONObject flow=GatewayClient.json(wire.request("POST","/api/v1/connections/"+account+"/auth/start",new JSONObject().put("redirect_uri",redirect).toString()));
                URI url=new URI(flow.getString("url"));Map<String,String> query=parse(url.getRawQuery());
                if(!"https".equals(url.getScheme())||!"auth.openai.com".equals(url.getHost())||url.getUserInfo()!=null||url.getFragment()!=null||!"/api/accounts/authorize".equals(url.getPath())||!redirect.equals(query.get("redirect_uri"))||!flow.getString("state").equals(query.get("state")))throw new IOException();
                main.post(()->{if(!closed&&!activity.isDestroyed()&&!activity.isFinishing())try{activity.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url.toString())));}catch(Exception unavailable){try{socket.close();}catch(IOException ignored){}}});
                long deadline=System.currentTimeMillis()+300000;
                while(!closed&&System.currentTimeMillis()<deadline){
                    socket.setSoTimeout((int)Math.max(1,deadline-System.currentTimeMillis()));
                    try(Socket incoming=socket.accept()){
                        incoming.setSoTimeout(5000);BufferedReader reader=new BufferedReader(new InputStreamReader(incoming.getInputStream(),StandardCharsets.US_ASCII));
                        String line=boundedLine(reader),host="";if(line==null)continue;String[] first=line.split(" ");int bytes=line.length();String header;
                        while((header=boundedLine(reader))!=null&&!header.isEmpty()){bytes+=header.length();if(bytes>16384)throw new IOException();if(header.toLowerCase(Locale.ROOT).startsWith("host:"))host=header.substring(5).trim();}
                        boolean valid=first.length==3&&first[0].equals("GET")&&host.equals("127.0.0.1:"+socket.getLocalPort());
                        URI callback=valid?new URI(first[1]):null;if(callback==null||callback.isAbsolute()||callback.getRawAuthority()!=null||!"/auth/callback".equals(callback.getPath())){respond(incoming,404,"Страница не найдена.");continue;}
                        Map<String,String> values=parse(callback.getRawQuery());String state=values.getOrDefault("state","");
                        if(!MessageDigest.isEqual(state.getBytes(StandardCharsets.UTF_8),flow.getString("state").getBytes(StandardCharsets.UTF_8))){respond(incoming,400,"Вход не подтверждён.");continue;}
                        JSONObject complete=new JSONObject().put("flow_id",flow.getString("flow_id")).put("state",state).put("code",values.getOrDefault("code","")).put("client_id",values.getOrDefault("client_id","")).put("error",values.getOrDefault("error",""));
                        JSONObject answer=GatewayClient.json(wire.request("POST","/api/v1/connections/"+account+"/auth/complete",complete.toString()));
                        result=answer.optString("status").equals("connected")?"Аккаунт подключён. Обновите список моделей.":"Вход выполнен, но доступ к плану не разрешён. Повторите вход и проверьте разрешения.";
                        respond(incoming,200,"Вход обработан. Вернитесь в WileyAI.");break;
                    }
                }
            }catch(Exception problem){/* OAuth URL/code/token must never be copied into diagnostics. */}
            finally{listener=null;String message=result;main.post(()->{if(!closed&&!activity.isDestroyed())done.accept(message);});}
        });
    }
    private static String boundedLine(Reader reader)throws IOException{StringBuilder line=new StringBuilder();int c;while((c=reader.read())!=-1){if(c=='\n')return line.toString();if(c!='\r')line.append((char)c);if(line.length()>12000)throw new IOException();}return line.length()==0?null:line.toString();}
    private static Map<String,String> parse(String raw)throws Exception{Map<String,String> result=new HashMap<>();if(raw==null||raw.length()>12000)throw new IOException();for(String item:raw.split("&")){String[] pair=item.split("=",2);String key=URLDecoder.decode(pair[0],"UTF-8"),value=pair.length>1?URLDecoder.decode(pair[1],"UTF-8"):"";if(result.put(key,value)!=null)throw new IOException();}return result;}
    private static void respond(Socket socket,int status,String message)throws IOException{byte[] body=("<!doctype html><html lang=ru><meta charset=utf-8><meta name=referrer content=no-referrer><p>"+message+"</p></html>").getBytes(StandardCharsets.UTF_8);OutputStream out=socket.getOutputStream();out.write(("HTTP/1.1 "+status+" Result\r\nContent-Type: text/html; charset=utf-8\r\nContent-Security-Policy: default-src 'none'\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: "+body.length+"\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.write(body);out.flush();}
    @Override public void close(){closed=true;ServerSocket socket=listener;if(socket!=null)try{socket.close();}catch(IOException ignored){}worker.shutdown();}
}
