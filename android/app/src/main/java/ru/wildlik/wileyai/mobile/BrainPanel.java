package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.content.*;
import android.provider.Settings;
import android.widget.*;
import org.json.*;
import java.util.*;

/** Everyday model choice first. The optional Gateway is kept under additional connections. */
final class BrainPanel {
    private final Activity activity;private final MobileUi ui;private final SettingsRepository settings;private final ModelManager models;private final Runnable local,api,gateway,selected;
    private TextView status,screenStatus;
    private final java.util.concurrent.ExecutorService worker=java.util.concurrent.Executors.newSingleThreadExecutor();private boolean closed;private AccountLogin accountLogin;
    private void post(Runnable task){activity.runOnUiThread(()->{if(!closed&&!activity.isDestroyed())task.run();});}
    BrainPanel(Activity activity,MobileUi ui,Runnable local,Runnable api,Runnable gateway,Runnable selected){this.activity=activity;this.ui=ui;this.local=local;this.api=api;this.gateway=gateway;this.selected=selected;settings=new SettingsRepository(activity);models=new ModelManager(activity);}
    void render(LinearLayout parent){
        status=ui.text("Основной мозг: "+models.label(),17,ui.theme.accentText);parent.addView(status);
        ui.link(parent,"Локальные модели","Qwen на телефоне · загрузка и параметры",local);
        ui.link(parent,"Облачные модели","API, ключи и выбор модели",api);
        parent.addView(ui.text("Автомаршрут: простые вопросы остаются на телефоне. Остальные идут выбранной модели. Для Gateway действует ручной выбор.",14,ui.theme.secondary));
        parent.addView(ui.button(settings.preferences.getBoolean("brain_auto_route",false)?"Настроить или отключить автомаршрут":"Настроить автомаршрут",this::automaticRouting));
        LinearLayout accounts=ui.disclosure(parent,"Вход через аккаунт");
        ui.link(accounts,"ChatGPT","Экспериментальный прямой вход",this::account);
        LinearLayout advanced=ui.disclosure(parent,"Дополнительные подключения");
        ui.link(advanced,"Свой Gateway","Подключение к своему серверу",gateway);
    }

    private void automaticRouting(){
        var dialog=ui.dialog().setTitle("Автоматический выбор модели");
        var source=models.selected();
        if(source==BrainProvider.Kind.REMOTE_GATEWAY){
            dialog.setMessage("Для Gateway используется выбранная вручную модель.");
        }else{
            String binding=models.binding();
            boolean local=source==BrainProvider.Kind.LOCAL;
            dialog.setMessage(local
                ?"Простые вопросы пойдут локальной Qwen без инструментов. Для сложных запросов будет использована выбранная модель, сейчас это локальная Qwen."
                :"Простые вопросы пойдут локальной Qwen. Разрешить отправлять текущий сложный запрос источнику «"+models.label()+"»? История, профиль и память не отправляются. Для инструментов действует отдельное разрешение.");
            if(local||!binding.isEmpty())dialog.setPositiveButton("Включить",(d,w)->{
                if(!binding.equals(models.binding()))return;
                settings.preferences.edit().putBoolean("brain_auto_route",true)
                    .putString("brain_auto_consent_binding",local?"":binding).apply();
                status.setText("Автомаршрут включён · "+models.label());
            });
        }
        dialog.setNegativeButton("Отключить",(d,w)->{
            settings.preferences.edit().putBoolean("brain_auto_route",false).remove("brain_auto_consent_binding").apply();
            status.setText("Основной мозг: "+models.label());
        }).setNeutralButton("Закрыть",null).show();
    }

    void renderModelExtras(LinearLayout parent){
        status=ui.text("Основной мозг: "+models.label(),15,ui.theme.secondary);
        parent.addView(status);
        parent.addView(ui.button("Проверить подключение и инструменты модели",this::probe));
        parent.addView(ui.button("Резервная модель",()->ui.dialog().setTitle("Резервный мозг").setSingleChoiceItems(new String[]{"Не выбирать","Локальная Qwen · переключение вручную"},settings.preferences.getBoolean("brain_reserve_local",false)?1:0,(d,index)->{settings.preferences.edit().putBoolean("brain_reserve_local",index==1).apply();d.dismiss();}).setNegativeButton("Закрыть",null).show()));
        if(settings.preferences.getBoolean("brain_reserve_local",false))parent.addView(ui.button("Перейти на резервную локальную модель",()->{models.local();selected.run();status.setText("Основной мозг: "+models.label());}));
    }

    void toolPermissions(LinearLayout parent){
        ui.setting(parent,"Предлагать действия по запросу",settings.preferences.getBoolean("brain_tools_enabled",true),
            on->settings.preferences.edit().putBoolean("brain_tools_enabled",on).apply());
        status=ui.text("",14,ui.theme.secondary);
        parent.addView(status);
        refreshToolConsent();
        parent.addView(ui.button("Разрешить передачу результатов выбранной модели",()->{
            if(models.selected()==BrainProvider.Kind.LOCAL){status.setText("Для локальной модели данные инструментов остаются на телефоне.");return;}
            String binding=models.binding();if(binding.isEmpty()){status.setText("Сначала настройте источник и выберите модель.");return;}
            ui.dialog().setTitle("Передавать результаты инструментов?").setMessage("Выбранная модель будет получать результаты вызванных инструментов: названия найденных приложений, состояние плеера, устройства и запрошенные вами напоминания. Пароли, контакты и содержимое экрана не передаются. Изменения и чтение личных данных показываются на подтверждение плана.\n\nИсточник: "+models.label()).setNegativeButton("Отмена",null).setPositiveButton("Разрешить этому источнику",(d,w)->{settings.preferences.edit().putString("brain_tool_consent_binding",binding).apply();refreshToolConsent();}).show();
        }));
        parent.addView(ui.button("Отозвать согласие",()->{settings.preferences.edit().remove("brain_tool_consent_binding").apply();refreshToolConsent();}));
    }
    private void refreshToolConsent(){
        String binding=models.binding();
        boolean allowed=!binding.isEmpty()&&binding.equals(settings.preferences.getString("brain_tool_consent_binding",""));
        status.setText(models.selected()==BrainProvider.Kind.LOCAL?"Локальная обработка · данные инструментов остаются на телефоне":
            models.label()+(allowed?" · передача разрешена":" · передача запрещена"));
    }
    void renderScreenSettings(LinearLayout view){
        screenStatus=ui.text("",15,ui.theme.text);
        view.addView(screenStatus);
        refreshScreenStatus();
        view.addView(ui.text("WileyAI читает структуру окна только по вашему запросу. Сторонним приложениям нужно отдельное разрешение. Фильтры скрывают поля ввода и признаки секретов, но не могут распознать все личные данные: не разрешайте банковские, платёжные приложения и переписки. Отключить доступ можно здесь и в специальных возможностях Android.",14,ui.theme.secondary));
        ui.setting(view,"Разрешить наблюдение по запросу",settings.preferences.getBoolean("screen_observation_enabled",false),
            on->settings.preferences.edit().putBoolean("screen_observation_enabled",on).apply());
        view.addView(ui.button("Специальные возможности Android",()->activity.startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))));
        view.addView(ui.button("Разрешённые приложения",this::screenApps));
        view.addView(ui.button("Открыть безопасный тестовый экран",()->activity.startActivity(new Intent(activity,ScreenFixtureActivity.class))));
        view.addView(ui.button("Проверить текущий экран",()->ScreenDispatcher.dispatch(activity,null,"опиши экран",()->!activity.isDestroyed(),text->ui.dialog().setTitle("Проверка экрана").setMessage(text).setPositiveButton("Закрыть",null).show())));
    }
    void refreshScreenStatus(){
        if(screenStatus!=null)screenStatus.setText("Разрешение Android: "+(ScreenObservationService.enabled(activity)?"включено":"выключено")
            +" · служба: "+(ScreenObservationService.running()?"подключена":"не подключена"));
    }
    void screenApps(){
        var pm=activity.getPackageManager();var candidates=pm.queryIntentActivities(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER),0);
        Map<String,String> labels=new TreeMap<>();
        for(android.content.pm.ResolveInfo item:candidates){if(item.activityInfo==null||!item.activityInfo.enabled||!item.activityInfo.applicationInfo.enabled)continue;String pkg=item.activityInfo.packageName;if(ScreenPrivacy.trustedPackage(pkg,activity.getPackageName()))continue;String label=String.valueOf(item.loadLabel(pm));labels.putIfAbsent(pkg,label);}
        List<String> packages=new ArrayList<>(labels.keySet());packages.sort(Comparator.comparing(x->labels.get(x),String.CASE_INSENSITIVE_ORDER));
        String[] entries=new String[packages.size()];for(int i=0;i<packages.size();i++){String pkg=packages.get(i),label=labels.get(pkg);entries[i]=label+" · "+(ScreenPrivacy.protectedName(pkg)||ScreenPrivacy.protectedName(label)?"заблокировано":ScreenAppPermissions.allowed(activity,pkg)?"разрешено":"закрыто");}
        if(entries.length==0){ui.dialog().setMessage("Подходящие приложения не найдены.").setPositiveButton("Закрыть",null).show();return;}
        ui.dialog().setTitle("Наблюдение по приложениям").setItems(entries,(dialog,index)->{
            String pkg=packages.get(index),label=labels.get(pkg);
            if(ScreenAppPermissions.allowed(activity,pkg)){ScreenAppPermissions.revoke(activity,pkg);screenApps();return;}
            if(ScreenPrivacy.protectedName(pkg)||ScreenPrivacy.protectedName(label)){ui.dialog().setMessage("Это приложение похоже на чувствительное; наблюдение недоступно.").setPositiveButton("Понятно",null).show();return;}
            ui.dialog().setTitle("Разрешить наблюдение?").setMessage("«"+label+"»: по вашему запросу WileyAI сможет читать подписи и структуру его экрана локально. Фильтры не распознают все личные данные. Не разрешайте банковские приложения, переписки и приложения с секретами. Разрешение можно отозвать в этом списке.").setNegativeButton("Отмена",null).setPositiveButton("Разрешить",(d,w)->{if(!ScreenAppPermissions.grant(activity,pkg))ui.dialog().setMessage("Не удалось проверить приложение. Разрешение не выдано.").setPositiveButton("Закрыть",null).show();else screenApps();}).show();
        }).setNegativeButton("Закрыть",null).show();
    }
    static void personalData(Activity activity,MobileUi ui,LinearLayout view){int count=view.getChildCount();try(ToolsData data=new ToolsData(activity)){
        try(android.database.Cursor notes=data.getReadableDatabase().rawQuery("SELECT text,created FROM notes ORDER BY created DESC LIMIT 30",null)){while(notes.moveToNext())view.addView(ui.text("Заметка · "+notes.getString(0),15,ui.theme.text));}
        for(Map<String,Object> reminder:data.reminders())view.addView(ui.text("Напоминание · "+android.text.format.DateFormat.format("dd.MM HH:mm",(Long)reminder.get("due"))+"\n"+reminder.get("text")+(Boolean.TRUE.equals(reminder.get("delivered"))?" · доставлено":""),15,ui.theme.text));
    }if(view.getChildCount()==count)view.addView(ui.text("На телефоне пока нет записей.",14,ui.theme.secondary));}
    private void account(){ui.dialog().setTitle("ChatGPT на этом телефоне").setItems(new String[]{"Continue with ChatGPT","Выбрать модель / проверить вход","Отключить аккаунт"},(d,index)->{
        if(index==0){if(accountLogin!=null)accountLogin.close();accountLogin=new AccountLogin();status.setText("Открываю официальный вход OpenAI…");accountLogin.start(activity,settings,text->{status.setText(text);});}
        else if(index==1)accountModels();
        else ui.dialog().setTitle("Отключить ChatGPT?").setMessage("Будет удалена сессия с телефона и запрошен отзыв у OpenAI. История телефона сохранится.").setNegativeButton("Отмена",null).setPositiveButton("Отключить",(confirm,w)->{if(accountLogin!=null)accountLogin.close();worker.execute(()->{boolean revoked=new AccountSession(settings).disconnect();post(()->status.setText(revoked?"Аккаунт отключён.":"Сессия удалена с телефона. Отзыв у OpenAI не подтверждён; проверьте подключённые приложения в аккаунте."));});}).show();
    }).setNegativeButton("Закрыть",null).show();}
    private void accountModels(){status.setText("Проверяю прямое подключение ChatGPT…");worker.execute(()->{try{JSONArray catalog=new AccountSession(settings).models();if(catalog.length()==0)throw new Exception("Аккаунт не вернул доступных моделей. Фиктивный список не подставляется.");String[] labels=new String[catalog.length()];for(int i=0;i<labels.length;i++)labels[i]=catalog.getJSONObject(i).optString("display_name",catalog.getJSONObject(i).getString("slug"));post(()->{status.setText("Каталог получен. "+models.label()+".");ui.dialog().setTitle("Модели аккаунта ChatGPT").setItems(labels,(d,index)->{try{JSONObject profile=settings.readAccount(),model=catalog.getJSONObject(index);if(profile==null)throw new Exception();if(!model.getString("slug").equals(profile.optString("model_id")))profile.put("native_tools_verified",false);profile.put("model_id",model.getString("slug")).put("model_name",labels[index]);settings.saveAccount(profile);settings.preferences.edit().putBoolean("account_enabled",true).putBoolean("cloud_enabled",false).putBoolean("gateway_enabled",false).apply();selected.run();status.setText("Основной мозг: ChatGPT · "+labels[index]+". Для действий разрешите инструменты этому источнику.");}catch(Exception invalid){status.setText("Не удалось выбрать модель ChatGPT.");}}).setNegativeButton("Отмена",null).show();});}catch(Exception error){post(()->status.setText(error.getMessage()==null?"Прямой вход ChatGPT пока не подтверждён.":error.getMessage()));}});}
    private void probe(){if(models.selected()==BrainProvider.Kind.LOCAL){status.setText("Локальная модель: "+models.label()+". Инструменты используют проверяемый JSON; native tool calling не объявляется.");return;}if(models.selected()==BrainProvider.Kind.REMOTE_GATEWAY){status.setText("Проверка своего сервера доступна в дополнительных подключениях. Native tools Gateway не объявляются автоматически.");return;}
        ui.dialog().setTitle("Проверить модель?").setMessage("Будет отправлен короткий запрос с безопасным тестовым инструментом wiley_probe. Он не получает данных телефона и ничего не выполняет. Используется квота выбранного аккаунта.").setNegativeButton("Отмена",null).setPositiveButton("Проверить",(d,w)->{status.setText("Проверяю ответ модели и вызов тестового инструмента…");String binding=models.binding();worker.execute(()->{try{
            boolean account=models.selected()==BrainProvider.Kind.ACCOUNT_OAUTH;JSONObject config=account?settings.readAccount():settings.readCloud();if(config==null)throw new Exception("Сначала настройте выбранный источник.");BrainProvider provider=account?new AccountOAuthProvider(settings,true):new OfficialAPIProvider(new JSONObject(config.toString()).put("native_tools_verified",true));
            AndroidTools.Tool probe=new AndroidTools.Tool("wiley_probe","A harmless test: return code=7",AndroidTools.Risk.SAFE_READ,Map.of("code",new AndroidTools.Field("integer",true,7,7,List.of())));
            try{BrainProvider.Completion reply=provider.complete(List.of(Map.of("role","system","content","Call wiley_probe exactly once with code=7. Do not answer with text."),Map.of("role","user","content","Check connection")),List.of(probe),true,new BrainProvider.Cancellation(),s->{});boolean verified=reply.calls().size()==1&&reply.calls().get(0).name().equals("wiley_probe")&&StrictJson.parse(reply.calls().get(0).arguments()) instanceof Map<?,?> args&&args.size()==1&&Long.valueOf(7).equals(args.get("code"));if(!binding.equals(models.binding()))throw new Exception("Источник изменился. Проверка не применена.");config.put("native_tools_verified",verified);if(account)settings.saveAccount(config);else{boolean enabled=settings.preferences.getBoolean("cloud_enabled",false);settings.saveCloud(config);settings.preferences.edit().putBoolean("cloud_enabled",enabled).apply();}post(()->status.setText(verified?"Модель отвечает. Native tool calling проверен безопасным вызовом; действия требуют отдельного согласия.":"Модель ответила, но native tools не подтверждены. Используется строгий JSON с проверкой плана."));}finally{provider.close();}
        }catch(Exception error){post(()->status.setText(error.getMessage()==null?"Проверка не завершена.":error.getMessage()));}});}).show();
    }
    void close(){closed=true;if(accountLogin!=null)accountLogin.close();worker.shutdown();}
}
