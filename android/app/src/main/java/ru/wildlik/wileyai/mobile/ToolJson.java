package ru.wildlik.wileyai.mobile;

import org.json.*;
import java.util.*;

final class ToolJson {
    static Map<String,Object> result(AndroidTools.Result value){return Map.of("tool",value.tool(),"status",value.status(),"summary",value.summary(),"data",value.data());}
    static JSONArray schema(List<AndroidTools.Tool> tools)throws JSONException{JSONArray result=new JSONArray();for(AndroidTools.Tool tool:tools){JSONObject properties=new JSONObject();JSONArray required=new JSONArray();for(var entry:tool.fields().entrySet()){AndroidTools.Field field=entry.getValue();JSONObject value=new JSONObject().put("type",field.type());if(field.type().equals("integer"))value.put("minimum",field.min()).put("maximum",field.max());else{value.put("minLength",field.min()).put("maxLength",field.max());if(!field.values().isEmpty())value.put("enum",new JSONArray(field.values()));}properties.put(entry.getKey(),value);if(field.required())required.put(entry.getKey());}
        result.put(new JSONObject().put("type","function").put("function",new JSONObject().put("name",tool.name()).put("description",tool.description()).put("parameters",new JSONObject().put("type","object").put("properties",properties).put("required",required).put("additionalProperties",false))));}return result;}
    static String text(List<Map<String,Object>> messages){StringBuilder value=new StringBuilder();for(var message:messages){String role=(String)message.get("role");if(role.equals("system"))value.append(message.get("content")).append('\n');else value.append(role).append(": ").append(message.getOrDefault("content","")).append('\n');}return value.toString();}
    private ToolJson(){}
}
