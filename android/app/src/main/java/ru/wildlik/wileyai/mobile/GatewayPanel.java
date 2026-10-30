package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.text.InputType;
import android.widget.*;
import org.json.*;
import java.util.*;

/** Account management is separate from the chat surface; unsupported services remain visibly unavailable. */
final class GatewayPanel {
    private final Activity activity;private final MobileUi ui;private final SettingsRepository settings;private final GatewayClient client;private final Runnable localModels;
    private LinearLayout accounts;private TextView status;private boolean closed;private GatewayLogin login;
    GatewayPanel(Activity activity,MobileUi ui,GatewayClient client,Runnable localModels){this.activity=activity;this.ui=ui;this.client=client;this.localModels=localModels;settings=new SettingsRepository(activity);}
    void render(LinearLayout parent){
        status=ui.text("",15,ui.theme.accentText);parent.addView(status);
        ui.link(parent,"Удалённые серверы","Ваш WileyAI Gateway · HTTPS и клиентский токен",this::server);
        ui.link(parent,"Веб-аккаунты","Собственные аккаунты и поддержанные способы входа",()->providers("web"));
        ui.link(parent,"Официальные API","Необязательные источники, заданные владельцем Gateway",()->providers("official_api"));
        ui.link(parent,"Бесплатные провайдеры","Проверяемая квота и доступность; без обещания безлимита",()->providers("keyless"));
        ui.link(parent,"Локальные модели","Работают на телефоне без Gateway",localModels);
        parent.addView(ui.button("Обновить подключение и аккаунты",this::refresh));
        parent.addView(ui.button("Диалоги на сервере",this::serverHistory));
        accounts=ui.vertical();parent.addView(accounts);
        parent.addView(ui.button("Вернуться к локальному разговору",()->{settings.preferences.edit().putBoolean("gateway_enabled",false).putBoolean("cloud_enabled",false).putBoolean("account_enabled",false).apply();status.setText("Выбрана локальная модель телефона. Подключения сохранены.");}));
        LinearLayout recovery=ui.disclosure(parent,"Оборвавшийся ответ");
        recovery.addView(ui.text("После обрыва ответ продолжает сохраняться на Gateway. Восстановление читает тот же job; новый запрос к нейросети не отправляется. Если подтверждение создания job потерялось, используется тот же request_id.",14,ui.theme.secondary));
        recovery.addView(ui.button("Восстановить последний ответ",this::resume));
        recovery.addView(ui.button("Отменить последний запрос",()->client.cancelPending(text->{if(!closed)status.setText(text);})));
        parent.addView(ui.button("Убрать неотправленные вложения",()->{
            try{if(client.busy()||settings.readGatewayPending()!=null){error("Сначала завершите или отмените запрос.");return;}JSONObject profile=settings.readGateway();if(profile==null)return;JSONArray files=profile.optJSONArray("pending_attachments");profile.remove("pending_attachments");settings.saveGateway(profile,false);if(files!=null)for(int i=0;i<files.length();i++){String id=files.optString(i);if(id.matches("[a-f0-9]{32}"))client.request("DELETE","/api/v1/attachments/"+id,null,value->{},this::error);}status.setText("Очередь вложений очищена.");}catch(Exception failure){error("Не удалось очистить очередь вложений.");}
        }));
        ui.card(parent,"Где находятся данные","Локальная история остаётся на телефоне. Выбранный Gateway хранит зашифрованную серверную историю и сессии подключённых аккаунтов. Голос распознаётся на Android. Команды телефону выполняются локально; текст нейросети не исполняется как команда.");
        refresh();
    }
    private void error(String text){if(!closed)status.setText(text);}
    void refresh(){
        if(closed||status==null)return;
        try{JSONObject profile=settings.readGateway();if(profile==null){status.setText("Удалённый Gateway не настроен");return;}status.setText("Проверяю свой Gateway…");}
        catch(Exception failure){error("Не удалось открыть настройку Gateway. Настройте сервер заново.");return;}
        client.request("GET","/api/v1/info",null,info->{if(closed)return;if(info.optInt("protocol")!=1){error("Версия протокола Gateway не поддерживается этим приложением.");return;}status.setText((info.optBoolean("test_mode")?"ТЕСТОВЫЙ сервер · ":"Gateway подключён · ")+info.optString("version"));
            client.request("GET","/api/v1/connections",null,value->{if(closed)return;accounts.removeAllViews();JSONArray list=value.optJSONArray("connections");if(list==null||list.length()==0){accounts.addView(ui.text("Аккаунтов пока нет. Откройте «Веб-аккаунты» и выберите поддержанный вход.",14,ui.theme.secondary));return;}
                for(int i=0;i<list.length();i++){JSONObject account=list.optJSONObject(i);if(account==null)continue;ui.link(accounts,account.optString("label"),state(account.optString("status")),()->account(account));}
            },this::error);
        },this::error);
    }
    private static String state(String value){return switch(value){case "connected"->"Подключено";case "configured"->"Настроено · требуется проверка";case "session_expired"->"Сессия истекла";case "plan_permission_required"->"Нужно разрешение на использование плана";case "rate_limited","quota_exceeded"->"Лимит достигнут";case "region_unavailable"->"Недоступно в регионе";case "authorization_required"->"Требуется авторизация";default->"Проверить подключение";};}
    private void server(){
        LinearLayout form=ui.vertical();ui.padded(form,12);EditText address=ui.field("https://gateway.example.com"),token=ui.field("Клиентский токен своего Gateway");address.setSingleLine(true);token.setSingleLine(true);token.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        try{JSONObject value=settings.readGateway();if(value!=null){address.setText(value.optString("url"));token.setText(value.optString("token"));}}catch(Exception ignored){}
        form.addView(address);form.addView(token);form.addView(ui.text("Это ваш сервер, работающий независимо от домашнего ПК. Токен Gateway выдаёт владелец сервера; он не является платным API-ключом нейросети. Не вводите сюда пароль или cookies ChatGPT/других сервисов.",14,ui.theme.secondary));
        AlertDialog dialog=ui.dialog().setTitle("Свой WileyAI Gateway").setView(form).setNegativeButton("Отмена",null).setNeutralButton("Отключить на телефоне",(d,w)->{settings.preferences.edit().remove("gateway_profile").putBoolean("gateway_enabled",false).apply();accounts.removeAllViews();status.setText("Сервер отключён на телефоне. Аккаунты на сервере не удалены.");}).setPositiveButton("Сохранить",null).show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{try{JSONObject profile=new JSONObject().put("url",address.getText().toString().trim()).put("token",token.getText().toString().trim());settings.saveGateway(profile,true);dialog.dismiss();refresh();}catch(Exception error){address.setError("Нужны корректный HTTPS-адрес и токен Gateway.");}});
    }
    private void providers(String category){
        client.request("GET","/api/v1/providers",null,value->{if(closed)return;JSONArray catalog=value.optJSONArray("providers");List<JSONObject> rows=new ArrayList<>();if(catalog!=null)for(int i=0;i<catalog.length();i++){JSONObject row=catalog.optJSONObject(i);if(row==null)continue;String kind=row.optString("category");if(category.equals("web")?(kind.equals("web")||kind.equals("oauth")||kind.equals("coding")):kind.equals(category))rows.add(row);}
            if(rows.isEmpty()){error("В этой категории сервер пока не предоставляет доступных адаптеров.");return;}
            String[] names=rows.stream().map(row->row.optString("name")+"\n"+(row.optBoolean("available")?row.optBoolean("experimental")?"Экспериментальный вход":"Добавить подключение":"Пока недоступно")).toArray(String[]::new);
            ui.dialog().setTitle("Добавить нейросеть").setItems(names,(d,index)->{
                JSONObject row=rows.get(index);if(!row.optBoolean("available")){ui.dialog().setTitle(row.optString("name")).setMessage(row.optString("description")).setPositiveButton("Понятно",null).show();return;}
                LinearLayout form=ui.vertical();ui.padded(form,12);EditText label=ui.field("Название подключения");label.setText(row.optString("name"));form.addView(label);EditText credential=ui.field("Ключ этого необязательного API");credential.setSingleLine(true);credential.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);if(category.equals("official_api"))form.addView(credential);
                ui.dialog().setTitle(row.optString("name")).setMessage(row.optString("description")+"\n\nВаш собственный Gateway получит сессию выбранного аккаунта. Сообщения отправляются провайдеру только при вашем обращении. Доступные модели и квота определяются аккаунтом.").setView(form).setNegativeButton("Отмена",null).setPositiveButton("Подключить",(confirm,which)->{
                    try{JSONObject body=new JSONObject().put("provider_id",row.getString("id")).put("label",label.getText().toString()).put("consent",true);if(category.equals("official_api"))body.put("credential",credential.getText().toString().trim());client.request("POST","/api/v1/connections",body,result->{if(closed)return;if(row.optString("id").equals("chatgpt"))authorize(result.optString("id"));else refresh();},this::error);}catch(Exception invalid){error("Не удалось подготовить подключение.");}
                }).show();
            }).setNegativeButton("Закрыть",null).show();
        },this::error);
    }
    private void account(JSONObject account){
        String id=account.optString("id");if(!id.matches("[a-f0-9]{32}"))return;
        ui.dialog().setTitle(account.optString("label")).setItems(new String[]{"Выбрать модель","Войти заново","Отключить и удалить авторизацию"},(d,index)->{
            if(index==0)models(account);
            else if(index==1){if(account.optString("provider_id").equals("chatgpt"))authorize(id);else error("Для этого источника авторизация настраивается при подключении.");}
            else ui.dialog().setTitle("Отключить аккаунт?").setMessage("Сессия будет удалена с вашего Gateway. История диалогов удаляется отдельно.").setNegativeButton("Отмена",null).setPositiveButton("Отключить",(confirm,w)->client.request("DELETE","/api/v1/connections/"+id,null,result->{try{JSONObject selected=settings.readGateway();if(selected!=null&&id.equals(selected.optString("connection_id")))settings.preferences.edit().putBoolean("gateway_enabled",false).apply();}catch(Exception ignored){}refresh();if(!result.optBoolean("revoked_upstream",false))error("Авторизация удалена с Gateway. Отзыв у провайдера не подтверждён; проверьте его настройки подключённых приложений.");},this::error)).show();
        }).setNegativeButton("Закрыть",null).show();
    }
    private void authorize(String id){
        try{JSONObject profile=settings.readGateway();if(profile==null)throw new Exception();if(login!=null)login.close();login=new GatewayLogin();status.setText("Открываю официальный вход в браузере…");login.start(activity,profile,id,text->{if(!closed){status.setText(text);refresh();}});}catch(Exception invalid){error("Сначала настройте свой Gateway.");}
    }
    private static boolean usable(JSONObject model,String feature){JSONObject features=model.optJSONObject("capabilities"),value=features==null?null:features.optJSONObject(feature);return value!=null&&(value.optString("state").equals("verified")||value.optString("state").equals("advertised"));}
    private void models(JSONObject account){
        String id=account.optString("id");client.request("GET","/api/v1/connections/"+id+"/models?refresh=true",null,value->{if(closed)return;JSONArray models=value.optJSONArray("models");if(models==null||models.length()==0){error("Аккаунт не вернул доступных моделей. Пустой каталог не заменяется выдуманными ID.");return;}
            String[] names=new String[models.length()];for(int i=0;i<models.length();i++){JSONObject model=models.optJSONObject(i);names[i]=model.optString("name")+"\n"+(usable(model,"vision")?"Изображения · ":"")+(usable(model,"file_upload")?"Файлы · ":"")+(usable(model,"web_search")?"Поиск · ":"")+(usable(model,"native_tools")?"Инструменты · ":"")+"функции по каталогу аккаунта";}
            ui.dialog().setTitle("Модели · "+account.optString("label")).setItems(names,(d,index)->select(account,models.optJSONObject(index))).setNegativeButton("Отмена",null).show();
        },this::error);
    }
    private void select(JSONObject account,JSONObject model){
        if(model==null)return;LinearLayout form=ui.vertical();ui.padded(form,12);Switch search=new Switch(activity);search.setText("Поиск в интернете");search.setTextColor(ui.theme.text);if(usable(model,"web_search"))form.addView(search);
        JSONArray modes=model.optJSONArray("reasoning_modes");Spinner reasoning=new Spinner(activity);List<String> labels=new ArrayList<>();labels.add("Режим по умолчанию");if(modes!=null)for(int i=0;i<modes.length();i++)labels.add(modes.optString(i));reasoning.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,labels));if(labels.size()>1)form.addView(reasoning);
        ui.dialog().setTitle(model.optString("name")).setMessage("Использовать этот аккаунт и модель для чата и голосового разговора? Сообщения будут проходить через ваш Gateway к выбранному провайдеру. Неподтверждённые функции остаются недоступны.").setView(form).setNegativeButton("Отмена",null).setPositiveButton("Использовать",(d,w)->{
            try{JSONObject profile=settings.readGateway();if(profile==null)throw new Exception();profile.put("connection_id",account.getString("id")).put("model_id",model.getString("id")).put("model_name",model.optString("name")).put("provider_name",account.optString("label")).put("capabilities",model.optJSONObject("capabilities")).put("web_search",search.isChecked()).remove("pending_attachments");
                if(reasoning.getSelectedItemPosition()>0)profile.put("reasoning_mode",labels.get(reasoning.getSelectedItemPosition()));else profile.remove("reasoning_mode");settings.saveGateway(profile,false);settings.preferences.edit().putBoolean("gateway_enabled",true).putBoolean("cloud_enabled",false).putBoolean("account_enabled",false).apply();status.setText("Выбрано: "+account.optString("label")+" · "+model.optString("name"));
            }catch(Exception invalid){error("Не удалось сохранить выбранную модель.");}
        }).show();
    }
    private void resume(){client.resume(new LocalLlm.Listener(){public void state(String value){error(value);}public void partial(String value){error(value.substring(Math.max(0,value.length()-500)));}public void done(String value,boolean stopped){if(!closed)ui.dialog().setTitle("Восстановленный ответ").setMessage(value).setPositiveButton("Закрыть",null).show();}public void error(String value){GatewayPanel.this.error(value);}public void finished(){}});}
    private void serverHistory(){client.request("GET","/api/v1/conversations",null,result->{if(closed)return;JSONArray list=result.optJSONArray("conversations");if(list==null||list.length()==0){error("Диалогов на этом Gateway пока нет.");return;}String[] labels=new String[list.length()];for(int i=0;i<labels.length;i++){JSONObject item=list.optJSONObject(i);labels[i]=item.optString("model_id")+" · сообщений: "+item.optInt("message_count")+"\n"+android.text.format.DateFormat.format("dd.MM.yyyy HH:mm",(long)(item.optDouble("created_at")*1000));}ui.dialog().setTitle("Диалоги Gateway").setItems(labels,(d,index)->{
        String id=list.optJSONObject(index).optString("id");if(!id.matches("[a-f0-9]{32}"))return;client.request("GET","/api/v1/conversations/"+id,null,value->{if(closed)return;LinearLayout content=ui.vertical();ui.padded(content,12);JSONArray messages=value.optJSONArray("messages");if(messages!=null)for(int i=Math.max(0,messages.length()-30);i<messages.length();i++){JSONObject message=messages.optJSONObject(i);if(message==null)continue;TextView text=ui.text((message.optString("role").equals("user")?"Вы: ":"Помощник: ")+message.optString("content"),15,ui.theme.text);text.setTextIsSelectable(true);content.addView(text);JSONArray citations=message.optJSONArray("citations");if(citations!=null)for(int j=0;j<citations.length();j++){JSONObject source=citations.optJSONObject(j);if(source!=null){TextView citation=ui.text(source.optString("title")+"\n"+source.optString("url"),13,ui.theme.accentText);citation.setTextIsSelectable(true);content.addView(citation);}}}ScrollView scroll=new ScrollView(activity);scroll.addView(content);
            ui.dialog().setTitle("История Gateway · последние 30 сообщений").setView(scroll).setNegativeButton("Закрыть",null).setNeutralButton("Удалить с сервера",(dialog,w)->{
                try{JSONObject pending=settings.readGatewayPending();if(pending!=null&&id.equals(pending.optString("conversation_id"))){error("Сначала восстановите или отмените запрос этого диалога.");return;}}catch(Exception ignored){error("Не удалось проверить незавершённый запрос.");return;}
                ui.dialog().setTitle("Удалить серверную историю?").setMessage("Этот диалог и его события будут удалены с выбранного Gateway. История телефона удаляется отдельно.").setNegativeButton("Отмена",null).setPositiveButton("Удалить",(confirm,w2)->client.request("DELETE","/api/v1/conversations/"+id,null,deleted->{error("Диалог удалён с Gateway.");},this::error)).show();
            }).show();
        },this::error);
    }).setNegativeButton("Закрыть",null).show();},this::error);}
    void close(){closed=true;if(login!=null)login.close();}
}
