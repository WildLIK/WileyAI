package ru.wildlik.wileyai.mobile;

import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Own OpenAI SIWC registration/session, entirely on Android; never reads another app's credentials. */
final class AccountSession {
    static final String AUTH="https://auth.openai.com/api/accounts/authorize",TOKEN="https://auth.openai.com/api/accounts/oauth/token",ISSUER="https://auth.openai.com",RESOURCE="https://api.openai.com/v1";
    static final String SCOPES="openid profile email offline_access resource.invoke chatgpt.tokens.use.direct";
    private static final Object LOCK=new Object();
    final SettingsRepository settings;
    AccountSession(SettingsRepository settings){this.settings=settings;}
    static JSONObject request(String method,String address,String token,String form)throws Exception{
        URI uri=new URI(address);if(!"https".equals(uri.getScheme())||!Set.of("auth.openai.com","api.openai.com").contains(uri.getHost())||uri.getUserInfo()!=null||uri.getFragment()!=null||uri.getQuery()!=null||uri.getPort()!=-1&&uri.getPort()!=443)throw new Exception("Неподтверждённый адрес OpenAI.");HttpURLConnection connection=(HttpURLConnection)uri.toURL().openConnection();
        try{connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(12000);connection.setReadTimeout(25000);connection.setRequestMethod(method);if(token!=null)connection.setRequestProperty("Authorization","Bearer "+token);if(form!=null){connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/x-www-form-urlencoded");byte[] body=form.getBytes(StandardCharsets.UTF_8);connection.setFixedLengthStreamingMode(body.length);try(OutputStream output=connection.getOutputStream()){output.write(body);}}
            int code=connection.getResponseCode();if(code!=200&&code!=201&&code!=204)throw new Exception(code==429?"OpenAI сообщил об ограничении запросов.":code==401||code==403?"OpenAI не разрешил доступ. Проверьте аккаунт, регион и разрешение использовать план.":"OpenAI не завершил запрос. HTTP "+code+".");InputStream stream=connection.getInputStream();try(ByteArrayOutputStream bytes=new ByteArrayOutputStream();InputStream input=stream){byte[] buffer=new byte[4096];int count;while((count=input.read(buffer))!=-1){if(bytes.size()+count>2*1024*1024)throw new IOException();bytes.write(buffer,0,count);}return bytes.size()==0?new JSONObject():new JSONObject(bytes.toString("UTF-8"));}
        }catch(IOException error){throw new Exception("Не удалось установить защищённое соединение с OpenAI. Проверьте интернет, VPN и дату телефона.");}finally{connection.disconnect();}
    }
    static String form(Map<String,String> fields)throws Exception{StringBuilder value=new StringBuilder();for(var field:fields.entrySet()){if(value.length()>0)value.append('&');value.append(URLEncoder.encode(field.getKey(),"UTF-8")).append('=').append(URLEncoder.encode(field.getValue(),"UTF-8"));}return value.toString();}
    static Map<?,?> identity(String idToken,String client,String nonce,String subject)throws Exception{
        JSONObject discovery=request("GET",ISSUER+"/.well-known/openid-configuration",null,null);if(!ISSUER.equals(discovery.optString("issuer"))||!(ISSUER+"/.well-known/jwks.json").equals(discovery.optString("jwks_uri")))throw new Exception("Не удалось подтвердить сервер входа OpenAI.");
        Object jwks=StrictJson.parse(request("GET",discovery.getString("jwks_uri"),null,null).toString());if(!(jwks instanceof Map<?,?> keys))throw new Exception("Некорректные ключи подписи OpenAI.");
        try{return JwtIdentity.validate(idToken,client,nonce,subject,keys,System.currentTimeMillis()/1000);}catch(Exception error){throw new Exception("Не удалось подтвердить подпись и личность аккаунта ChatGPT. Вход не сохранён.");}
    }
    static JSONObject credentials(JSONObject result,JSONObject previous)throws Exception{
        String access=result.optString("access_token"),type=result.optString("token_type");long seconds=result.optLong("expires_in",0);if(access.isEmpty()||access.length()>32000||!type.equalsIgnoreCase("bearer")||seconds<=0||seconds>365L*86400)throw new Exception("OpenAI не выдал действительную сессию.");JSONObject value=new JSONObject(previous.toString());value.put("access_token",access).put("refresh_token",result.optString("refresh_token",previous.optString("refresh_token"))).put("expires_at",System.currentTimeMillis()+seconds*1000);
        if(result.has("scope"))value.put("scope",result.getString("scope"));if(result.has("id_token"))value.put("id_token",result.getString("id_token"));if(!Arrays.asList(value.optString("scope").split(" ")).contains("chatgpt.tokens.use.direct"))throw new Exception("Аккаунт не разрешил использовать план ChatGPT. Повторите вход с этим разрешением.");return value;
    }
    String token()throws Exception{synchronized(LOCK){JSONObject value=settings.readAccount();if(value==null||value.optString("access_token").isEmpty())throw new Exception("Войдите в ChatGPT в «Настройки → Мозг».");if(value.optLong("expires_at")<=System.currentTimeMillis()+60000){if(value.optString("refresh_token").isEmpty())throw new Exception("Сессия ChatGPT истекла. Войдите заново.");JSONObject result=request("POST",TOKEN,null,form(Map.of("grant_type","refresh_token","client_id",value.getString("client_id"),"refresh_token",value.getString("refresh_token"),"resource",RESOURCE)));if(result.has("id_token"))identity(result.getString("id_token"),value.getString("client_id"),null,value.getString("subject"));value=credentials(result,value);settings.saveAccount(value);}return value.getString("access_token");}}
    JSONArray models()throws Exception{JSONObject response=request("GET",RESOURCE+"/models",token(),null);JSONArray source=response.optJSONArray("models"),models=new JSONArray();if(source==null)throw new Exception("OpenAI вернул несовместимый каталог моделей.");for(int i=0;i<Math.min(source.length(),500);i++){JSONObject item=source.optJSONObject(i);if(item!=null&&item.optString("visibility").equals("list")&&!item.optString("slug").isEmpty())models.put(item);}return models;}
    boolean disconnect(){synchronized(LOCK){boolean revoked=false;try{JSONObject value=settings.readAccount();if(value!=null&&!value.optString("refresh_token").isEmpty()){JSONObject discovery=request("GET",ISSUER+"/.well-known/openid-configuration",null,null);String endpoint=discovery.optString("revocation_endpoint");URI uri=new URI(endpoint);if(!ISSUER.equals(discovery.optString("issuer"))||!ISSUER.equals(uri.getScheme()+"://"+uri.getHost())||uri.getQuery()!=null)throw new Exception();request("POST",endpoint,null,form(Map.of("token",value.getString("refresh_token"),"token_type_hint","refresh_token","client_id",value.getString("client_id"))));}revoked=true;}catch(Exception ignored){}finally{settings.clearAccount();}return revoked;}}
}
