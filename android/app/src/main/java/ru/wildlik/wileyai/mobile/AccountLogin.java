package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.*;
import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Direct SIWC on this Android host. System browser + one-use loopback PKCE, no Gateway. */
final class AccountLogin implements AutoCloseable {
    private final ExecutorService worker=Executors.newSingleThreadExecutor();private volatile boolean closed;private volatile ServerSocket server;
    private static String random(){byte[] value=new byte[32];new SecureRandom().nextBytes(value);return Base64.getUrlEncoder().withoutPadding().encodeToString(value);}
    void start(Activity activity,SettingsRepository settings,Consumer<String> done){worker.execute(()->{String result="Вход не завершён. Проверьте доступность OpenAI и повторите вход.";
        try(ServerSocket socket=new ServerSocket()){
            server=socket;socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),0));String redirect="http://127.0.0.1:"+socket.getLocalPort()+"/auth/callback",state=random(),nonce=random(),verifier=random()+random();
            String host=settings.preferences.getString("siwc_android_host","");if(host.isEmpty()){host="urn:uuid:"+UUID.randomUUID();if(!settings.preferences.edit().putString("siwc_android_host",host).commit())throw new Exception();}
            JSONObject old=settings.readAccount();if(old==null)old=new JSONObject();String client=old.optString("client_id",old.optString("pending_client_id",""));Map<String,String> params=new LinkedHashMap<>();params.put("client_id",client.isEmpty()?"dynamic_agent_client":client);params.put("ext_agent_host_id",host);params.put("response_type","code");params.put("redirect_uri",redirect);params.put("scope",AccountSession.SCOPES);params.put("resource",AccountSession.RESOURCE);params.put("state",state);params.put("nonce",nonce);params.put("code_challenge_method","S256");params.put("code_challenge",Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.getBytes(StandardCharsets.US_ASCII))));
            if(client.isEmpty())params.put("agent_name_hint","WileyAI Android");else if(!old.optString("id_token").isEmpty())params.put("id_token_hint",old.getString("id_token"));
            String address=AccountSession.AUTH+"?"+AccountSession.form(params);new Handler(Looper.getMainLooper()).post(()->{if(!closed&&!activity.isDestroyed())try{activity.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(address)));}catch(Exception unavailable){try{socket.close();}catch(IOException ignored){}}});long deadline=System.currentTimeMillis()+300000;
            while(!closed&&System.currentTimeMillis()<deadline){socket.setSoTimeout((int)Math.max(1,deadline-System.currentTimeMillis()));try(Socket incoming=socket.accept()){
                incoming.setSoTimeout(5000);BufferedReader reader=new BufferedReader(new InputStreamReader(incoming.getInputStream(),StandardCharsets.US_ASCII));String first=line(reader);if(first==null)continue;String header,receivedHost="";int bytes=first.length();while((header=line(reader))!=null&&!header.isEmpty()){bytes+=header.length();if(bytes>16384)throw new IOException();if(header.toLowerCase(Locale.ROOT).startsWith("host:"))receivedHost=header.substring(5).trim();}
                String[] request=first.split(" ");URI uri=request.length==3&&request[0].equals("GET")&&receivedHost.equals("127.0.0.1:"+socket.getLocalPort())?new URI(request[1]):null;
                if(uri==null||uri.isAbsolute()||uri.getRawAuthority()!=null||uri.getFragment()!=null||!uri.getPath().equals("/auth/callback")){respond(incoming,404,"Страница не найдена.");continue;}
                Map<String,String> query=parse(uri.getRawQuery());if(!MessageDigest.isEqual(state.getBytes(StandardCharsets.UTF_8),query.getOrDefault("state","").getBytes(StandardCharsets.UTF_8))){respond(incoming,400,"Неверный запрос входа.");continue;}
                if(query.containsKey("error")){respond(incoming,400,"Вход отменён. Вернитесь в WileyAI.");result="OpenAI не выдал разрешение на вход или использование плана. Можно продолжить локально.";break;}
                String issued=client.isEmpty()?query.getOrDefault("client_id",""):client;String code=query.getOrDefault("code","");if(!issued.matches("[A-Za-z0-9_-]{1,250}")||issued.equals("dynamic_agent_client")||code.isEmpty()||code.length()>8192)throw new Exception();
                if(client.isEmpty()){old.put("pending_client_id",issued);settings.saveAccount(old);}
                try{JSONObject tokens=AccountSession.request("POST",AccountSession.TOKEN,null,AccountSession.form(Map.of("grant_type","authorization_code","client_id",issued,"code",code,"code_verifier",verifier,"redirect_uri",redirect,"resource",AccountSession.RESOURCE)));Map<?,?> claims=AccountSession.identity(tokens.getString("id_token"),issued,nonce,client.isEmpty()?null:old.optString("subject",null));
                    JSONObject value=AccountSession.credentials(tokens,new JSONObject().put("client_id",issued).put("host_id",host).put("subject",claims.get("sub")).put("email",claims.get("email")).put("id_token",tokens.getString("id_token")));if(closed)throw new IOException("Вход отменён.");settings.saveAccount(value);result="Аккаунт подтверждён. Выберите модель из каталога OpenAI.";respond(incoming,200,"Вход завершён. Вернитесь в WileyAI и выберите модель.");
                }catch(Exception error){result=error.getMessage()==null?"Не удалось подтвердить вход. Попробуйте снова.":error.getMessage();respond(incoming,400,"WileyAI не завершил вход. Подробности доступны в приложении.");}break;
            }}
        }catch(Exception ignored){/* Never log OAuth URLs, codes, claims or tokens. */}finally{server=null;String message=result;new Handler(Looper.getMainLooper()).post(()->{if(!closed&&!activity.isDestroyed())done.accept(message);});}
    });}
    private static String line(Reader reader)throws IOException{StringBuilder out=new StringBuilder();int c;while((c=reader.read())!=-1){if(c=='\n')return out.toString();if(c!='\r')out.append((char)c);if(out.length()>12000)throw new IOException();}return out.length()==0?null:out.toString();}
    private static Map<String,String> parse(String raw)throws Exception{if(raw==null||raw.length()>12000)throw new IOException();Map<String,String> result=new HashMap<>();for(String item:raw.split("&")){String[] parts=item.split("=",2);String key=URLDecoder.decode(parts[0],"UTF-8"),value=parts.length>1?URLDecoder.decode(parts[1],"UTF-8"):"";if(result.put(key,value)!=null)throw new IOException();}return result;}
    private static void respond(Socket socket,int code,String message)throws IOException{byte[] body=("<!doctype html><meta charset=utf-8><meta name=referrer content=no-referrer><p>"+message+"</p>").getBytes(StandardCharsets.UTF_8);OutputStream out=socket.getOutputStream();out.write(("HTTP/1.1 "+code+" Result\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nContent-Security-Policy: default-src 'none'\r\nConnection: close\r\nContent-Length: "+body.length+"\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.write(body);out.flush();}
    public void close(){closed=true;ServerSocket current=server;if(current!=null)try{current.close();}catch(IOException ignored){}worker.shutdown();}
}
