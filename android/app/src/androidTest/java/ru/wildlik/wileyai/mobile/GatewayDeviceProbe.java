package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.content.*;
import android.database.sqlite.SQLiteDatabase;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import javax.net.ssl.*;

/** Disposable fixture server. No personal provider account, production profile, or trust-store changes. */
final class GatewayDeviceProbe {
    private static void check(boolean value,String stage){if(!value)throw new AssertionError("Gateway device: "+stage);}
    private static String id(){return UUID.randomUUID().toString().replace("-","");}
    private static JSONObject json(GatewayWire.Reply reply)throws Exception{return GatewayClient.json(reply);}
    private static View find(View view,String label){if(view instanceof TextView&&label.contentEquals(((TextView)view).getText()))return view;if(view instanceof ViewGroup){ViewGroup group=(ViewGroup)view;for(int i=0;i<group.getChildCount();i++){View found=find(group.getChildAt(i),label);if(found!=null)return found;}}return null;}
    private static void click(Activity activity,String label){View view=find(activity.getWindow().getDecorView(),label);check(view!=null,"UI control "+label);while(!view.isClickable()&&view.getParent() instanceof View)view=(View)view.getParent();check(view.isClickable(),"UI clickable");view.performClick();}
    private static void main(Instrumentation runner,Runnable action){AtomicReference<Throwable> error=new AtomicReference<>();runner.runOnMainSync(()->{try{action.run();}catch(Throwable failure){error.set(failure);}});if(error.get()!=null)throw new AssertionError("Device UI assertion",error.get());}
    static String run(Instrumentation runner,Context context,JSONObject fixture)throws Exception{
        JSONObject report=new JSONObject();String dbName="gateway-v10-migration-test.db",chat="";
        SettingsRepository isolated=new SettingsRepository(context,"gateway-v10-test");isolated.preferences.edit().clear().commit();
        GatewayClient[] client={null};Activity activity=null;
        try{
            context.deleteDatabase(dbName);
            try(SQLiteDatabase old=context.openOrCreateDatabase(dbName,0,null)){
                old.execSQL(LocalChatRepository.CHATS);old.execSQL(LocalChatRepository.MESSAGES);old.execSQL(LocalChatRepository.INDEX);
                old.execSQL("INSERT INTO chats(id,title,draft,updated) VALUES('old','Сохранить','Черновик',1)");old.execSQL("INSERT INTO messages(chat_id,role,content,created) VALUES('old','user','История',1)");old.setVersion(1);
            }
            try(LocalChatRepository migrated=new LocalChatRepository(context,dbName)){
                check(migrated.getReadableDatabase().getVersion()==2,"schema v1 to v2");check(migrated.chat("old").draft().equals("Черновик"),"draft preserved");
                migrated.recover("old","same-run","Ответ");migrated.recover("old","same-run","Ответ");check(migrated.messages("old").size()==2,"recovery deduplicated");migrated.delete("old");migrated.recover("old","other-run","Ответ");check(migrated.chats().isEmpty(),"deleted chat not resurrected");
            }
            report.put("migration_preserves_draft_and_history",true).put("recovery_deduplicated",true);
            JSONObject profile=new JSONObject().put("url",fixture.getString("url")).put("token",fixture.getString("token"));
            isolated.saveGateway(profile,true);String ciphertext=isolated.preferences.getString("gateway_profile","");
            check(!ciphertext.contains(fixture.getString("token")),"no plaintext token");check(isolated.readGateway().getString("token").equals(fixture.getString("token")),"Keystore decrypt");
            isolated.saveGatewayPending(new JSONObject().put("test","pending"));isolated.preferences.edit().putString("gateway_pending",ciphertext).commit();boolean aad=false;try{isolated.readGatewayPending();}catch(Exception expected){aad=true;}check(aad,"AAD rejects cross-profile substitution");isolated.clearGatewayPending();
            report.put("android_keystore_roundtrip",true).put("profile_aad_isolation",true);
            KeyStore trust=KeyStore.getInstance(KeyStore.getDefaultType());trust.load(null);
            byte[] cert=fixture.getString("certificate").getBytes(java.nio.charset.StandardCharsets.US_ASCII);
            trust.setCertificateEntry("disposable-test-certificate",CertificateFactory.getInstance("X.509").generateCertificate(new ByteArrayInputStream(cert)));
            TrustManagerFactory managers=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());managers.init(trust);
            SSLContext tls=SSLContext.getInstance("TLS");tls.init(null,managers.getTrustManagers(),null);
            GatewayClient.WireFactory wires=value->new GatewayWire(value.getString("url"),value.getString("token"),url->{HttpsURLConnection connection=(HttpsURLConnection)url.openConnection();connection.setSSLSocketFactory(tls.getSocketFactory());return connection;});
            boolean rejected=false;try{new GatewayWire(profile.getString("url"),profile.getString("token")).request("GET","/api/v1/info",null);}catch(SSLException expected){rejected=true;}check(rejected,"production TLS rejects untrusted fixture certificate");
            GatewayWire wire=wires.create(profile);check(json(wire.request("GET","/api/v1/info",null)).getInt("protocol")==1,"HTTPS protocol");
            String connection=json(wire.request("POST","/api/v1/connections",new JSONObject().put("provider_id","test-provider").put("consent",true).toString())).getString("id");
            JSONArray models=json(wire.request("GET","/api/v1/connections/"+connection+"/models?refresh=true",null)).getJSONArray("models");
            check(models.length()==1,"dynamic catalog");JSONObject model=models.getJSONObject(0);check(!GatewayClient.supports(model,"vision"),"unknown vision disabled");
            profile.put("connection_id",connection).put("model_id",model.getString("id")).put("capabilities",model.getJSONObject("capabilities"));isolated.saveGateway(profile,false);isolated.preferences.edit().putBoolean("gateway_enabled",true).commit();
            try(LocalChatRepository repository=new LocalChatRepository(context)){chat=repository.submit("","Проверка Gateway через USB");}
            main(runner,()->client[0]=new GatewayClient(context,isolated,wires));
            List<LocalChatRepository.Message> messages;try(LocalChatRepository repository=new LocalChatRepository(context)){messages=repository.messages(chat);}
            Result first=new Result();String phoneChat=chat;
            main(runner,()->client[0].generate(phoneChat,messages,first));check(first.finished.await(25,TimeUnit.SECONDS),"generation deadline");check(first.error.get()==null,"generation without error");check(first.partial.get()>0&&first.answer.get()!=null&&first.answer.get().contains("через USB"),"real HTTPS SSE deltas");
            check(isolated.readGatewayPending()==null&&client[0].savedResponse(),"persist before clearing pending");
            try(LocalChatRepository repository=new LocalChatRepository(context)){check(repository.messages(chat).size()==2,"normal local answer saved once");repository.append(chat,"user","test-citation");}
            String conversation=json(wire.request("POST","/api/v1/conversations",new JSONObject().put("connection_id",connection).put("model_id",model.getString("id")).toString())).getString("id");
            JSONObject body=new JSONObject().put("request_id",id()).put("text","test-citation");
            JSONObject pending=new JSONObject().put("phone_chat",chat).put("conversation_id",conversation).put("body",body).put("url",profile.getString("url")).put("connection_id",connection).put("model_id",model.getString("id"));isolated.saveGatewayPending(pending);
            String run=json(wire.request("POST","/api/v1/conversations/"+conversation+"/runs",body.toString())).getString("id");wire.events(run,0,event->{});
            // The device has no ACK/run_id: resume must reuse request_id, never regenerate.
            Result recovered=new Result();main(runner,()->client[0].resume(recovered));check(recovered.finished.await(25,TimeUnit.SECONDS),"resume deadline");check(recovered.error.get()==null&&recovered.answer.get().contains("https://example.com/source"),"citation preserved on recovery");
            check(json(wire.request("GET","/api/v1/conversations/"+conversation+"?limit=0",null)).getInt("message_count")==2,"lost ACK did not duplicate request");
            try(LocalChatRepository repository=new LocalChatRepository(context)){check(repository.messages(chat).size()==4,"resumed local answer saved once");}
            String attachment=json(wire.upload("POST","/api/v1/attachments","fixture".getBytes(java.nio.charset.StandardCharsets.UTF_8),"text/plain","fixture.txt")).getString("id");
            JSONObject unavailable=new JSONObject().put("request_id",id()).put("text","Файл").put("attachments",new JSONArray().put(attachment));check(wire.request("POST","/api/v1/conversations/"+conversation+"/runs",unavailable.toString()).status()==422,"unsupported file rejected");json(wire.request("DELETE","/api/v1/attachments/"+attachment,null));
            String cancelled=id();json(wire.request("POST","/api/v1/requests/"+cancelled+"/cancel","{}"));check(wire.request("POST","/api/v1/conversations/"+conversation+"/runs",new JSONObject().put("request_id",cancelled).put("text","не отправлять").toString()).status()==409,"cancel before ACK");
            report.put("physical_https_sse",true).put("default_tls_rejects_untrusted_certificate",true).put("lost_ack_recovered_without_regeneration",true).put("citations_preserved",true).put("capability_gate_and_cancel",true).put("partial_updates",first.partial.get());
            activity=runner.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));Activity screen=activity;
            main(runner,()->{click(screen,"Настройки");click(screen,"Мозг");click(screen,"Дополнительные подключения  ▸");click(screen,"Свой Gateway");for(String label:new String[]{"Удалённые серверы","Веб-аккаунты","Официальные API","Бесплатные провайдеры","Локальные модели","Диалоги на сервере"})check(find(screen.getWindow().getDecorView(),label)!=null,"connections UI "+label);});
            report.put("connections_categories_on_device",true).put("personal_provider_accounts_used",false);
            json(wire.request("DELETE","/api/v1/connections/"+connection,null));
            return report.toString();
        }finally{
            if(activity!=null){Activity screen=activity;main(runner,screen::finish);runner.waitForIdleSync();}
            if(client[0]!=null)main(runner,client[0]::close);
            if(!chat.isEmpty())try(LocalChatRepository repository=new LocalChatRepository(context)){repository.delete(chat);}
            isolated.preferences.edit().clear().commit();context.deleteDatabase(dbName);
        }
    }
    private static final class Result implements LocalLlm.Listener {
        final CountDownLatch finished=new CountDownLatch(1);final AtomicReference<String> answer=new AtomicReference<>(),error=new AtomicReference<>();final AtomicInteger partial=new AtomicInteger();
        public void state(String value){}public void partial(String value){partial.incrementAndGet();}public void done(String value,boolean stopped){answer.set(value);}public void error(String value){error.set(value);}public void finished(){finished.countDown();}
    }
    static String finalChecks(Instrumentation runner,Context context)throws Exception{
        JSONObject result=new JSONObject();
        try(LocalChatRepository repository=new LocalChatRepository(context)){
            result.put("schema",repository.getReadableDatabase().getVersion());
            for(String table:new String[]{"chats","messages"}){
                java.security.MessageDigest digest=java.security.MessageDigest.getInstance("SHA-256");int rows=0;
                try(android.database.Cursor cursor=repository.getReadableDatabase().rawQuery("SELECT * FROM "+table+" ORDER BY 1",null)){
                    while(cursor.moveToNext()){rows++;for(int column=0;column<cursor.getColumnCount();column++){digest.update((byte)cursor.getType(column));byte[] value=(cursor.isNull(column)?"":cursor.getString(column)).getBytes(java.nio.charset.StandardCharsets.UTF_8);digest.update(java.nio.ByteBuffer.allocate(4).putInt(value.length).array());digest.update(value);}}
                }
                StringBuilder hex=new StringBuilder();for(byte value:digest.digest())hex.append(String.format(java.util.Locale.ROOT,"%02x",value&255));result.put(table,new JSONObject().put("count",rows).put("sha256",hex.toString()));
            }
        }
        android.content.SharedPreferences production=context.getSharedPreferences("wiley-mobile",0),isolated=context.getSharedPreferences("gateway-v10-voice-test",0);
        android.content.SharedPreferences.Editor edit=isolated.edit().putString("offline_engine",production.getString("offline_engine",""));
        if(production.contains("offline_voice"))edit.putString("offline_voice",production.getString("offline_voice",""));
        edit.putFloat("offline_voice_rate",production.getFloat("offline_voice_rate",1f)).putFloat("offline_voice_pitch",production.getFloat("offline_voice_pitch",1f)).commit();
        LocalVoice[] voice={null};CountDownLatch ready=new CountDownLatch(1),spoken=new CountDownLatch(1);AtomicReference<String> error=new AtomicReference<>();AtomicInteger completions=new AtomicInteger();
        try{
            main(runner,()->{voice[0]=new LocalVoice(context,isolated,text->{error.set(text);ready.countDown();spoken.countDown();});voice[0].ready(ready::countDown);});
            check(ready.await(20,TimeUnit.SECONDS)&&error.get()==null,"current TTS ready");
            main(runner,()->voice[0].speakCompleted("Проверка Уайли на телефоне завершена.",()->{completions.incrementAndGet();spoken.countDown();}));
            check(spoken.await(20,TimeUnit.SECONDS)&&error.get()==null&&completions.get()==1,"current TTS completed once");
            result.put("tts_engine",production.getString("offline_engine","")).put("tts_completed_once",true).put("wake_phrase",production.getString("wake_phrase",WakePhrase.DEFAULT));
        }finally{if(voice[0]!=null)main(runner,voice[0]::close);isolated.edit().clear().commit();}
        return result.toString();
    }
}
