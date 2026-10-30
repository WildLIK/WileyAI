package ru.wildlik.wileyai.mobile;

import java.net.*;
import java.io.*;
import java.util.*;
import org.json.*;

/** Read the configured service's actual OpenAI-compatible catalog; no bundled model IDs. */
final class DirectModelCatalog {
    static JSONArray models(String endpoint,String key)throws Exception{
        CloudChat.validate(new JSONObject().put("endpoint",endpoint).put("key",key).put("model","catalog-only"));String base=endpoint.replaceAll("/+$","");if(base.endsWith("/chat/completions"))base=base.substring(0,base.length()-17);HttpURLConnection connection=(HttpURLConnection)new URL(base+"/models").openConnection();
        try{connection.setConnectTimeout(10000);connection.setReadTimeout(15000);connection.setInstanceFollowRedirects(false);if(!key.isEmpty())connection.setRequestProperty("Authorization","Bearer "+key);int code=connection.getResponseCode();if(code!=200)throw new Exception(code==404?"Сервис не предоставляет такой каталог. Введите ID модели из его официальной документации.":CloudChat.httpError(code));
            try(InputStream input=connection.getInputStream();ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1){if(output.size()+count>2*1024*1024)throw new IOException();output.write(buffer,0,count);}JSONArray list=new JSONObject(output.toString("UTF-8")).optJSONArray("data");if(list==null)throw new Exception("Каталог имеет другой формат. Введите ID модели вручную.");JSONArray clean=new JSONArray();Set<String> ids=new HashSet<>();for(int i=0;i<Math.min(list.length(),500);i++){JSONObject item=list.optJSONObject(i);String id=item==null?"":item.optString("id");if(id.matches("[A-Za-z0-9][A-Za-z0-9_./:@+\\-]{0,159}")&&ids.add(id))clean.put(new JSONObject().put("id",id).put("name",item.optString("name",id)));}if(clean.length()==0)throw new Exception("Источник не вернул доступных моделей.");return clean;}
        }catch(IOException error){throw new Exception("Не удалось прочитать модели через защищённое соединение.");}finally{connection.disconnect();}
    }
}
