package ru.wildlik.wileyai.mobile;

import android.net.Uri;
import android.os.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;

/** Documented Open-Meteo APIs, explicit city only. No device location or background collection. */
final class WeatherTool {
    private static JSONObject read(String address,BooleanSupplier active)throws Exception{
        if(!active.getAsBoolean())throw new InterruptedIOException();HttpURLConnection connection=(HttpURLConnection)new URL(address).openConnection();connection.setConnectTimeout(8000);connection.setReadTimeout(10000);connection.setInstanceFollowRedirects(false);
        try{if(connection.getResponseCode()!=200)throw new IOException();try(InputStream stream=connection.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream()){byte[] buffer=new byte[4096];int count;while((count=stream.read(buffer))!=-1){if(!active.getAsBoolean()||bytes.size()+count>128*1024)throw new IOException();bytes.write(buffer,0,count);}return new JSONObject(bytes.toString("UTF-8"));}}finally{connection.disconnect();}
    }
    static void fetch(String city,BooleanSupplier active,Consumer<AndroidTools.Result> callback){ExecutorService worker=Executors.newSingleThreadExecutor();worker.execute(()->{AndroidTools.Result result;try{
        JSONArray found=read(Uri.parse("https://geocoding-api.open-meteo.com/v1/search").buildUpon().appendQueryParameter("name",city).appendQueryParameter("count","3").appendQueryParameter("language","ru").appendQueryParameter("format","json").build().toString(),active).optJSONArray("results");
        if(found==null||found.length()==0)throw new IllegalArgumentException();JSONObject place=found.getJSONObject(0);
        if(found.length()>1&&found.getJSONObject(1).optString("name").equalsIgnoreCase(place.getString("name")))throw new IllegalArgumentException();
        String label=place.getString("name")+", "+place.optString("admin1",place.optString("country"));
        JSONObject weather=read(Uri.parse("https://api.open-meteo.com/v1/forecast").buildUpon().appendQueryParameter("latitude",String.valueOf(place.getDouble("latitude"))).appendQueryParameter("longitude",String.valueOf(place.getDouble("longitude"))).appendQueryParameter("current","temperature_2m,apparent_temperature,weather_code,wind_speed_10m").appendQueryParameter("timezone","auto").build().toString(),active);
        JSONObject current=weather.getJSONObject("current");double degrees=current.getDouble("temperature_2m");String text=label+": "+Math.round(degrees)+" °C, ощущается как "+Math.round(current.getDouble("apparent_temperature"))+" °C. Данные Open-Meteo на "+current.getString("time").replace('T',' ')+" ("+weather.optString("timezone")+").";
        result=new AndroidTools.Result("get_weather","verified",text,Map.of("city",label,"temperature_c",degrees,"time",current.getString("time"),"source","https://open-meteo.com/"));
    }catch(IllegalArgumentException error){result=new AndroidTools.Result("get_weather","needs_input","Не удалось однозначно найти город. Уточните его название и регион.",Map.of());}catch(Exception error){result=new AndroidTools.Result("get_weather","failed","Не удалось получить погоду. Проверьте интернет; локальные команды доступны.",Map.of());}finally{worker.shutdown();}AndroidTools.Result value=result;new Handler(Looper.getMainLooper()).post(()->callback.accept(value));});}
}
