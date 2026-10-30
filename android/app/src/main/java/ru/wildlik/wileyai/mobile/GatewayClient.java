package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.*;
import org.json.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** Remote runs have durable IDs; a broken SSE stream retries only reading, never generation. */
final class GatewayClient {
    private static final AtomicBoolean GENERATING=new AtomicBoolean();
    private final Context context;
    interface WireFactory { GatewayWire create(JSONObject profile) throws Exception; }
    private final WireFactory wires;
    private final SettingsRepository settings;private final Handler main=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newFixedThreadPool(2);private final AtomicBoolean busy=new AtomicBoolean();
    private volatile boolean closed,cancelled,stopRequested,savedResponse;private volatile GatewayWire active;private volatile String activeRun="";
    GatewayClient(Context context){this(context,new SettingsRepository(context),profile->new GatewayWire(profile.getString("url"),profile.getString("token")));}
    GatewayClient(Context context,SettingsRepository settings,WireFactory wires){this.context=context.getApplicationContext();this.settings=settings;this.wires=wires;}
    static boolean enabled(Context context){return context.getSharedPreferences("wiley-mobile",0).getBoolean("gateway_enabled",false);}
    boolean busy(){return busy.get();}
    boolean savedResponse(){return savedResponse;}
    private static String sourced(String text,Map<String,String> sources){StringBuilder value=new StringBuilder(text);for(Map.Entry<String,String> source:sources.entrySet())value.append("\n\n[").append(source.getValue().replace("]","")).append("](").append(source.getKey().replace(")","%29")).append(")");return value.toString();}
    private void post(Runnable callback){main.post(()->{if(!closed)callback.run();});}
    static JSONObject json(GatewayWire.Reply reply)throws Exception{
        JSONObject value;try{value=new JSONObject(reply.body());}catch(JSONException error){throw new Exception("Gateway вернул несовместимый ответ.");}
        if(reply.status()<200||reply.status()>=300){JSONObject problem=value.optJSONObject("error");throw new Exception(problem==null?"Ошибка Gateway HTTP "+reply.status():problem.optString("message","Ошибка Gateway"));}
        return value;
    }
    GatewayWire wire(JSONObject profile)throws Exception{return wires.create(profile);}
    void request(String method,String path,JSONObject body,Consumer<JSONObject> done,Consumer<String> error){
        worker.execute(()->{try{JSONObject profile=settings.readGateway();if(profile==null)throw new Exception("Настройте свой Gateway.");JSONObject result=json(wire(profile).request(method,path,body==null?null:body.toString()));post(()->done.accept(result));}catch(Exception failure){post(()->error.accept(safe(failure)));}});
    }
    private static String safe(Exception error){if(error instanceof javax.net.ssl.SSLException)return "Не удалось проверить HTTPS-сертификат Gateway.";if(error instanceof java.io.IOException)return "Не удалось связаться с Gateway. Проверьте интернет, адрес и сервер.";String message=error.getMessage();return message==null?"Ошибка Gateway.":message.substring(0,Math.min(500,message.length()));}
    static boolean supports(JSONObject profile,String feature){JSONObject caps=profile.optJSONObject("capabilities"),cap=caps==null?null:caps.optJSONObject(feature);return cap!=null&&(cap.optString("state").equals("verified")||cap.optString("state").equals("advertised"));}
    void upload(android.net.Uri uri,String name,String mime,Consumer<String> done){
        worker.execute(()->{String message;try{
            JSONObject profile=settings.readGateway();if(profile==null||!enabledFromSettings())throw new Exception("Выберите модель Gateway.");
            if(!supports(profile,mime.startsWith("image/")?"vision":"file_upload"))throw new Exception("Этот тип вложения не подтверждён выбранной моделью.");
            if(settings.readGatewayPending()!=null)throw new Exception("Сначала завершите или отмените предыдущий запрос.");
            JSONArray queue=profile.optJSONArray("pending_attachments");if(queue==null)queue=new JSONArray();if(queue.length()>=5)throw new Exception("Можно прикрепить до пяти файлов.");
            byte[] bytes;try(java.io.InputStream input=context.getContentResolver().openInputStream(uri);java.io.ByteArrayOutputStream output=new java.io.ByteArrayOutputStream()){
                if(input==null)throw new Exception("Файл недоступен.");byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1){if(output.size()+count>10*1024*1024)throw new Exception("Файл превышает 10 МиБ.");output.write(buffer,0,count);}bytes=output.toByteArray();
            }
            JSONObject attachment=json(wire(profile).upload("POST","/api/v1/attachments",bytes,mime,name));JSONObject latest=settings.readGateway();
            if(latest==null||!profile.optString("url").equals(latest.optString("url"))||!profile.optString("connection_id").equals(latest.optString("connection_id"))||!profile.optString("model_id").equals(latest.optString("model_id"))){json(wire(profile).request("DELETE","/api/v1/attachments/"+attachment.getString("id"),null));throw new Exception("Модель изменилась. Вложение не прикреплено.");}
            queue.put(attachment.getString("id"));latest.put("pending_attachments",queue);settings.saveGateway(latest,false);message="Прикреплено файлов: "+queue.length()+". Файл сохранён на вашем Gateway; провайдер получит его после отправки сообщения.";
        }catch(Exception failure){message=safe(failure);}String result=message;post(()->done.accept(result));});
    }
    void generate(String phoneChat,List<LocalChatRepository.Message> context,LocalLlm.Listener listener){
        begin(phoneChat,context,listener,false);
    }
    void resume(LocalLlm.Listener listener){begin("",Collections.emptyList(),listener,true);}
    private void begin(String phoneChat,List<LocalChatRepository.Message> context,LocalLlm.Listener listener,boolean resume){
        if(closed)return;
        if(!GENERATING.compareAndSet(false,true)){post(()->{listener.error("Другой запрос Gateway ещё выполняется. Дождитесь ответа.");listener.finished();});return;}
        if(!busy.compareAndSet(false,true)){GENERATING.set(false);return;}cancelled=false;stopRequested=false;savedResponse=false;activeRun="";
        worker.execute(()->{
            StringBuilder answer=new StringBuilder();LinkedHashMap<String,String> sources=new LinkedHashMap<>();String error=null;boolean completed=false;JSONObject profile=null;
            try{
                profile=settings.readGateway();if(profile==null||(!resume&&!enabledFromSettings()))throw new Exception("Подключите Gateway и выберите модель.");
                String account=profile.getString("connection_id"),model=profile.getString("model_id");if(!account.matches("[a-f0-9]{32}"))throw new Exception("Выберите аккаунт Gateway.");
                GatewayWire wire=wire(profile);active=wire;
                JSONObject pending=settings.readGatewayPending();if(!resume&&pending!=null)throw new Exception("Есть незавершённый запрос Gateway. Откройте «Подключения» и восстановите либо отмените его.");
                if(resume&&(pending==null||!pending.optString("url").equals(profile.getString("url"))||!pending.optString("connection_id").equals(account)||!pending.optString("model_id").equals(model)))throw new Exception("Для восстановления выберите прежний сервер, аккаунт и модель. Новый запрос не отправлялся.");
                String binding="gateway_chat:"+profile.getString("url")+":"+phoneChat+":"+account+":"+model;
                String conversation=resume?pending.getString("conversation_id"):settings.preferences.getString(binding,"");
                if(!resume&&conversation.matches("[a-f0-9]{32}")){GatewayWire.Reply existing=wire.request("GET","/api/v1/conversations/"+conversation+"?limit=0",null);if(existing.status()==404){settings.preferences.edit().remove(binding).commit();conversation="";}else json(existing);}
                if(!resume&&!conversation.matches("[a-f0-9]{32}")){
                    JSONObject created=json(wire.request("POST","/api/v1/conversations",new JSONObject().put("connection_id",account).put("model_id",model).toString()));
                    conversation=created.getString("id");if(!conversation.matches("[a-f0-9]{32}"))throw new Exception("Некорректный ID диалога Gateway.");settings.preferences.edit().putString(binding,conversation).commit();
                }
                String text=context.isEmpty()?"":context.get(context.size()-1).content();
                JSONObject body=resume?pending.getJSONObject("body"):new JSONObject().put("request_id",UUID.randomUUID().toString().replace("-","")).put("text",text);
                if(!resume){
                    JSONObject options=new JSONObject();if(profile.optBoolean("web_search",false))options.put("web_search",true);if(!profile.optString("reasoning_mode").isEmpty())options.put("reasoning_mode",profile.getString("reasoning_mode"));body.put("options",options);
                    JSONArray attachments=profile.optJSONArray("pending_attachments");if(attachments!=null&&attachments.length()>0)body.put("attachments",attachments);
                    JSONArray seed=new JSONArray();for(int i=Math.max(0,context.size()-9);i<context.size()-1;i++){LocalChatRepository.Message message=context.get(i);String content=message.content();seed.put(new JSONObject().put("role",message.role()).put("content",content.substring(0,Math.min(4000,content.length()))));}body.put("context",seed);
                }
                // Persist before POST: the acknowledgement can be lost without the request being lost.
                if(!resume)settings.saveGatewayPending(new JSONObject().put("phone_chat",phoneChat).put("conversation_id",conversation).put("body",body).put("url",profile.getString("url")).put("connection_id",account).put("model_id",model));
                JSONObject run=resume&&!pending.optString("run_id").isEmpty()?json(wire.request("GET","/api/v1/runs/"+pending.getString("run_id"),null)):json(wire.request("POST","/api/v1/conversations/"+conversation+"/runs",body.toString()));activeRun=run.getString("id");
                if(!activeRun.matches("[a-f0-9]{32}"))throw new Exception("Некорректный ID ответа Gateway.");
                settings.saveGatewayPending(new JSONObject().put("phone_chat",resume?pending.optString("phone_chat"):phoneChat).put("run_id",activeRun).put("conversation_id",conversation).put("body",body).put("url",profile.getString("url")).put("connection_id",account).put("model_id",model));
                if(cancelled)return;
                String runId=activeRun;long[] cursor={0};boolean[] terminal={false};String[] problem={null};int attempts=0;
                while(!cancelled&&!terminal[0]&&attempts++<3){
                    try{
                        active=wire;
                        wire.events(runId,cursor[0],event->{
                            cursor[0]=event.id();try{
                                JSONObject data=new JSONObject(event.data());
                                if(event.type().equals("message.delta")){answer.append(data.optString("text"));if(answer.length()>2*1024*1024)throw new IllegalStateException();String value=answer.toString();post(()->listener.partial(value));}
                                else if(event.type().equals("reasoning.summary"))post(()->listener.state("Модель размышляет…"));
                                else if(event.type().equals("citation.added")){String url=data.optString("url"),title=data.optString("title","Источник");try{java.net.URI uri=new java.net.URI(url);if("https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getUserInfo()==null)sources.put(url,title);}catch(Exception ignored){}}
                                else if(event.type().startsWith("run.")&&!event.type().equals("run.started")){terminal[0]=true;JSONObject failure=data.optJSONObject("error");if(!event.type().equals("run.completed"))problem[0]=failure==null?"Ответ остановлен.":failure.optString("message","Ответ прерван.");}
                            }catch(Exception invalid){throw new IllegalStateException("Некорректное событие Gateway.");}
                        });
                        if(!terminal[0]&&!cancelled){wire=wire(profile);post(()->listener.state("Восстанавливаю поток Gateway…"));}
                    }catch(java.io.IOException broken){if(cancelled)break;if(attempts>=3)throw broken;wire=wire(profile);post(()->listener.state("Восстанавливаю поток Gateway…"));}
                }
                if(!cancelled&&!terminal[0])throw new Exception("Поток оборвался. Частичный ответ сохранён на Gateway; повтор не отправлялся.");
                error=problem[0];completed=terminal[0];
                if(completed){
                    if(answer.length()>0){try(LocalChatRepository repository=new LocalChatRepository(this.context)){String target=resume?pending.optString("phone_chat"):phoneChat;repository.recover(target,activeRun,sourced(answer.toString(),sources)+(error==null?"":"\n\n"+error));savedResponse=true;}}
                    settings.clearGatewayPending();JSONObject latest=settings.readGateway();if(latest!=null&&latest.optString("url").equals(profile.optString("url"))&&latest.optString("connection_id").equals(account)&&latest.optString("model_id").equals(model)){latest.remove("pending_attachments");settings.saveGateway(latest,false);}
                }
            }catch(Exception failure){error=safe(failure);}
            finally{
                if(cancelled&&stopRequested&&profile!=null)cancelStored(profile);
                active=null;activeRun="";GENERATING.set(false);busy.set(false);String text=sourced(answer.toString(),sources),problem=error;boolean stopped=cancelled;
                post(()->{busy.set(false);if(!text.isEmpty())listener.done(text+(problem==null?"":"\n\n"+problem),stopped);else if(problem!=null)listener.error(problem);else listener.done("",stopped);listener.finished();});
            }
        });
    }
    private boolean enabledFromSettings(){return settings.preferences.getBoolean("gateway_enabled",false);}
    private void cancelStored(JSONObject profile){try{JSONObject pending=settings.readGatewayPending();if(pending==null||!profile.optString("url").equals(pending.optString("url")))return;String request=pending.getJSONObject("body").getString("request_id");json(wire(profile).request("POST","/api/v1/requests/"+request+"/cancel","{}"));settings.clearGatewayPending();}catch(Exception ignored){}}
    void cancel(){stopRequested=true;cancelled=true;GatewayWire wire=active;if(wire!=null)wire.cancel();}
    void cancelPending(Consumer<String> done){cancel();worker.execute(()->{String message;try{JSONObject profile=settings.readGateway(),pending=settings.readGatewayPending();if(profile==null||pending==null)throw new Exception("Незавершённого запроса нет.");if(!profile.optString("url").equals(pending.optString("url")))throw new Exception("Для отмены выберите прежний сервер.");String request=pending.getJSONObject("body").getString("request_id");json(wire(profile).request("POST","/api/v1/requests/"+request+"/cancel","{}"));settings.clearGatewayPending();message="Запрос остановлен на Gateway.";}catch(Exception failure){message=safe(failure);}String result=message;post(()->done.accept(result));});}
    void close(){closed=true;cancelled=true;GatewayWire wire=active;if(wire!=null)wire.cancel();worker.shutdown();}
}
