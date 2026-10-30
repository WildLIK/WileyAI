package ru.wildlik.wileyai.mobile;

import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.Consumer;

/** Documented Chat Completions. User-owned credentials, normal TLS, no provider fallback. */
class OfficialAPIProvider implements BrainProvider {
    protected final JSONObject config;
    OfficialAPIProvider(JSONObject config)throws Exception{CloudChat.validate(config);this.config=config;}
    public Kind kind(){return Kind.OFFICIAL_API;}public boolean nativeTools(){return config.optBoolean("native_tools_verified",false);}
    public Completion complete(List<Map<String,Object>> messages,List<AndroidTools.Tool> tools,boolean planning,Cancellation cancel,Consumer<String> status)throws Exception{
        String base=config.getString("endpoint").replaceAll("/+$","");HttpURLConnection connection=(HttpURLConnection)new URL(base.endsWith("/chat/completions")?base:base+"/chat/completions").openConnection();cancel.onCancel(connection::disconnect);
        try{cancel.check();connection.setRequestMethod("POST");connection.setDoOutput(true);connection.setConnectTimeout(12000);connection.setReadTimeout(45000);connection.setInstanceFollowRedirects(false);connection.setRequestProperty("Content-Type","application/json");if(!config.optString("key").isEmpty())connection.setRequestProperty("Authorization","Bearer "+config.getString("key"));
            JSONObject body=new JSONObject().put("model",config.getString("model")).put("messages",new JSONArray(messages)).put("stream",false);if(planning&&nativeTools()&&!tools.isEmpty())body.put("tools",ToolJson.schema(tools));byte[] bytes=body.toString().getBytes(StandardCharsets.UTF_8);connection.setFixedLengthStreamingMode(bytes.length);try(OutputStream output=connection.getOutputStream()){output.write(bytes);}int code=connection.getResponseCode();if(code!=200)throw new Exception(CloudChat.httpError(code));
            try(InputStream input=connection.getInputStream();ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] buffer=new byte[4096];int count;while((count=input.read(buffer))!=-1){cancel.check();if(output.size()+count>256*1024)throw new Exception("Ответ модели слишком большой.");output.write(buffer,0,count);}JSONObject choice=new JSONObject(output.toString("UTF-8")).getJSONArray("choices").getJSONObject(0);String finish=choice.optString("finish_reason");if(!Set.of("stop","tool_calls").contains(finish))throw new Exception("Модель остановила ответ до завершения. Действия не выполнялись.");JSONObject message=choice.getJSONObject("message");List<Call> calls=new ArrayList<>();JSONArray nativeCalls=message.optJSONArray("tool_calls");if(nativeCalls!=null){if(!nativeTools()||!planning||nativeCalls.length()>4)throw new Exception("Неожиданные инструменты провайдера. Действия не выполнялись.");Set<String> ids=new HashSet<>();for(int i=0;i<nativeCalls.length();i++){JSONObject call=nativeCalls.getJSONObject(i),function=call.getJSONObject("function");String id=call.getString("id");if(!id.matches("[A-Za-z0-9_-]{1,160}")||!ids.add(id)||!call.optString("type").equals("function"))throw new Exception("Некорректный вызов инструмента.");calls.add(new Call(id,function.getString("name"),function.getString("arguments")));}}
                Object content=message.opt("content");return new Completion(content instanceof String?(String)content:"",List.copyOf(calls));}
        }catch(javax.net.ssl.SSLException error){throw new Exception("Не удалось проверить HTTPS-сертификат облачного API.");}catch(IOException error){throw new Exception("Облачный API недоступен. Проверьте подключение; другой провайдер не выбирался.");}finally{connection.disconnect();}
    }
}
