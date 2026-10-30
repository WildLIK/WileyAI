package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.*;
import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Opt-in text-only Chat Completions connector. Model output is never executed as phone actions. */
final class CloudChat {
    private final SettingsRepository settings;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final Handler main=new Handler(Looper.getMainLooper());
    private final AtomicBoolean busy=new AtomicBoolean();
    private volatile boolean cancelled,closed;private volatile HttpURLConnection active;
    interface Connector {HttpURLConnection open(String address)throws IOException;}
    private final Connector connector;
    CloudChat(Context context){this(new SettingsRepository(context),address->(HttpURLConnection)new URL(address).openConnection());}
    CloudChat(SettingsRepository settings,Connector connector){this.settings=settings;this.connector=connector;}
    boolean busy(){return busy.get();}
    static boolean enabled(Context context){return context.getSharedPreferences("wiley-mobile",0).getBoolean("cloud_enabled",false);}
    static void validate(JSONObject config)throws Exception{
        URI uri=new URI(config.getString("endpoint"));
        if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null||uri.getPort()==0||uri.getPort()>65535)throw new Exception("Нужен HTTPS-адрес API без логина, параметров и фрагмента");
        if(!config.getString("model").matches("[A-Za-z0-9][A-Za-z0-9_./:@+\\-]{0,159}"))throw new Exception("Укажите ID модели из документации сервиса");
        String key=config.optString("key");if(key.length()>4096||key.matches("(?s).*[\\p{Cc}].*"))throw new Exception("Некорректный ключ API");
    }
    static JSONObject payload(String model,List<LocalChatRepository.Message> history)throws JSONException{
        JSONArray messages=new JSONArray();
        String system="Ты Уайли, русскоязычный помощник. Отвечай кратко и по делу. Команды телефону выполняет приложение отдельно. Не заявляй, что открыла приложение, изменила настройки или выполнила действие. У тебя нет доступа к экрану, микрофону и установленным приложениям.";
        if(!history.isEmpty()&&history.get(history.size()-1).content().toLowerCase(Locale.ROOT).matches("(?s).*(?:сейчас|сегодня|врем|дат|час).*"))system+=" Время телефона: "+java.time.ZonedDateTime.now()+".";
        messages.put(new JSONObject().put("role","system").put("content",system));
        int start=Math.max(0,history.size()-8);for(int i=start;i<history.size();i++){
            LocalChatRepository.Message message=history.get(i);if(!message.role().matches("user|assistant"))continue;
            String content=message.content();if(content.length()>4000)content=content.substring(0,4000);
            messages.put(new JSONObject().put("role",message.role()).put("content",content));
        }
        return new JSONObject().put("model",model).put("messages",messages).put("stream",false).put("max_tokens",512);
    }
    void generate(List<LocalChatRepository.Message> messages,LocalLlm.Listener listener){
        if(closed||!busy.compareAndSet(false,true))return;cancelled=false;List<LocalChatRepository.Message> history=new ArrayList<>(messages);
        worker.execute(()->{
            String answer=null,error=null;HttpURLConnection connection=null;
            try{
                JSONObject config=settings.readCloud();if(config==null||!settings.preferences.getBoolean("cloud_enabled",false))throw new Exception("Выберите облачное подключение в «Компоненты → Облачные чаты»");validate(config);
                String base=config.getString("endpoint").replaceAll("/+$","");String address=base.endsWith("/chat/completions")?base:base+"/chat/completions";
                connection=connector.open(address);active=connection;if(cancelled)return;
                connection.setConnectTimeout(12000);connection.setReadTimeout(45000);connection.setInstanceFollowRedirects(false);connection.setRequestMethod("POST");connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type","application/json; charset=utf-8");connection.setRequestProperty("Accept","application/json");
                if(!config.optString("key").isEmpty())connection.setRequestProperty("Authorization","Bearer "+config.getString("key"));
                byte[] body=payload(config.getString("model"),history).toString().getBytes(StandardCharsets.UTF_8);connection.setFixedLengthStreamingMode(body.length);
                try(OutputStream output=connection.getOutputStream()){output.write(body);}
                int status=connection.getResponseCode();if(status!=200)throw new Exception(httpError(status));
                try(InputStream input=connection.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream()){
                    byte[] buffer=new byte[4096];int count;while(!cancelled&&(count=input.read(buffer))!=-1){if(bytes.size()+count>256*1024)throw new Exception("Ответ сервиса слишком большой");bytes.write(buffer,0,count);}
                    if(!cancelled){JSONObject message=new JSONObject(bytes.toString(StandardCharsets.UTF_8.name())).getJSONArray("choices").getJSONObject(0).getJSONObject("message");
                        if(message.optJSONArray("tool_calls")!=null&&message.getJSONArray("tool_calls").length()>0)throw new Exception("Сервис вернул инструмент вместо текстового ответа. Действия не выполнялись.");
                        Object content=message.opt("content");if(!(content instanceof String)||((String)content).trim().isEmpty())throw new Exception("Сервис не вернул текст ответа");answer=((String)content).trim();
                    }
                }
            }catch(javax.net.ssl.SSLException tls){error="Не удалось проверить защищённое соединение с сервисом. Проверьте адрес и сертификат.";}
            catch(SocketTimeoutException timeout){error="Облачный сервис не ответил вовремя. Повторите позже.";}
            catch(JSONException protocol){error="Сервис вернул несовместимый формат Chat Completions.";}
            catch(Exception failure){error=failure instanceof IOException?"Облачный сервис недоступен. Проверьте интернет и адрес API.":failure.getMessage();}
            finally{
                if(connection!=null)connection.disconnect();active=null;String reply=answer,problem=error;boolean stopped=cancelled;
                main.post(()->{busy.set(false);if(closed)return;if(stopped)listener.done("",true);else if(problem!=null)listener.error(problem);else listener.done(reply==null?"":reply,false);listener.finished();});
            }
        });
    }
    static String httpError(int status){return switch(status){case 401,403->"Сервис отклонил авторизацию. Проверьте ключ и разрешение на модель.";case 402->"У сервиса закончился бесплатный лимит или баланс. Автоматического перехода на оплату нет.";case 429->"Сервис ограничил частоту запросов или исчерпан лимит. Повторите позже.";case 301,302,307,308->"API перенаправляет запрос. Укажите конечный HTTPS-адрес вручную.";default->"Ошибка облачного сервиса HTTP "+status+". Повторите позже.";};}
    void cancel(){cancelled=true;HttpURLConnection connection=active;if(connection!=null)connection.disconnect();}
    void close(){closed=true;cancel();worker.shutdown();}
}
