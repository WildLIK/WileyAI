package ru.wildlik.wileyai.mobile;

import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.Consumer;

/** Direct official SIWC Responses. No API key, VPS, backend-api, cookies or another client's registration. */
final class AccountOAuthProvider implements BrainProvider {
    private final SettingsRepository settings;private final AccountSession session;
    private final boolean probing;
    AccountOAuthProvider(SettingsRepository settings){this(settings,false);}
    AccountOAuthProvider(SettingsRepository settings,boolean probing){this.settings=settings;session=new AccountSession(settings);this.probing=probing;}
    public Kind kind(){return Kind.ACCOUNT_OAUTH;}
    public boolean nativeTools(){try{JSONObject profile=settings.readAccount();return probing||profile!=null&&profile.optBoolean("native_tools_verified",false);}catch(Exception error){return false;}}
    public Completion complete(List<Map<String,Object>> messages,List<AndroidTools.Tool> tools,boolean planning,Cancellation cancel,Consumer<String> status)throws Exception{
        JSONObject profile=settings.readAccount();if(profile==null||profile.optString("model_id").isEmpty())throw new Exception("Выберите модель ChatGPT в разделе «Мозг».");String token=session.token();HttpURLConnection connection=(HttpURLConnection)new URL(AccountSession.RESOURCE+"/responses").openConnection();cancel.onCancel(connection::disconnect);
        try{cancel.check();connection.setConnectTimeout(12000);connection.setReadTimeout(60000);connection.setInstanceFollowRedirects(false);connection.setRequestMethod("POST");connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/json");connection.setRequestProperty("Authorization","Bearer "+token);connection.setRequestProperty("Accept","text/event-stream");
            JSONArray input=new JSONArray();for(Map<String,Object> message:messages){String role=(String)message.get("role");if(role.equals("tool"))input.put(new JSONObject().put("type","function_call_output").put("call_id",message.get("tool_call_id")).put("output",message.get("content")));else if(message.get("provider_output") instanceof List<?> output){for(Object item:output)input.put(JSONObject.wrap(item));}else input.put(new JSONObject().put("role",role.equals("system")?"developer":role).put("content",message.getOrDefault("content","")));}
            JSONObject body=new JSONObject().put("model",profile.getString("model_id")).put("store",false).put("stream",true).put("input",input);
            if(planning&&nativeTools()&&!tools.isEmpty()){JSONArray functions=new JSONArray(),definitions=ToolJson.schema(tools);for(int i=0;i<definitions.length();i++){JSONObject function=definitions.getJSONObject(i).getJSONObject("function");function.put("type","function").put("strict",false);functions.put(function);}body.put("tools",new JSONArray().put(new JSONObject().put("type","namespace").put("name","wiley_android").put("description","User-approved local Android tools").put("tools",functions)));}
            byte[] bytes=body.toString().getBytes(StandardCharsets.UTF_8);connection.setFixedLengthStreamingMode(bytes.length);try(OutputStream output=connection.getOutputStream()){output.write(bytes);}int code=connection.getResponseCode();if(code!=200)throw new Exception(CloudChat.httpError(code));try(Reader reader=new InputStreamReader(connection.getInputStream(),StandardCharsets.UTF_8)){return ResponsesWire.read(reader,planning&&nativeTools(),cancel::check);}

        }catch(IOException error){throw new Exception("Прямое соединение с OpenAI прервалось. Действия по незавершённому ответу не выполнялись.");}finally{connection.disconnect();}
    }
}
