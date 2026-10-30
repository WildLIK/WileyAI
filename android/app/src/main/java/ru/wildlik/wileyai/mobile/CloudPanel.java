package ru.wildlik.wileyai.mobile;

import android.app.*;
import android.content.Intent;
import android.net.Uri;
import android.text.InputType;
import android.widget.*;
import org.json.JSONObject;

/** A configured account/bridge stays disabled until its destination is explicitly confirmed. */
final class CloudPanel {
    private final Activity activity;private final MobileUi ui;private final SettingsRepository settings;
    private TextView state;private Switch enabled;
    CloudPanel(Activity activity,MobileUi ui){this.activity=activity;this.ui=ui;settings=new SettingsRepository(activity);}
    void render(LinearLayout parent){
        state=ui.text("",16,ui.theme.accentText);parent.addView(state);
        ui.card(parent,"Как подключить API","Создайте ключ в официальном кабинете сервиса, укажите его HTTPS-адрес и выберите модель. Бесплатная квота может требовать ключ. Логин от сайта нейросети сюда не вводится. Для входа аккаунтом ChatGPT откройте «Настройки → Мозг».");
        parent.addView(ui.button("Gemini · API с бесплатной квотой",()->configure("https://generativelanguage.googleapis.com/v1beta/openai/")));
        parent.addView(ui.button("Настроить подключение",this::configure));
        enabled=new Switch(activity);enabled.setText("Облачный чат и голосовой разговор");enabled.setTextColor(ui.theme.text);enabled.setMinHeight(ui.dp(56));enabled.setChecked(CloudChat.enabled(activity));parent.addView(enabled);
        renderListener();
        ui.card(parent,"Источник ответов","После включения текстовый чат телефона и режим «давай поговорим» используют выбранный сервис. Выключите переключатель, чтобы вернуться к установленной локальной модели. Другой сервис автоматически не подставляется.");
        LinearLayout options=ui.disclosure(parent,"Сервисы и бесплатные ограничения");
        ui.link(options,"Получить ключ Gemini","Доступность и бесплатные лимиты зависят от региона, аккаунта и модели",()->open("https://aistudio.google.com/apikey"));
        ui.link(options,"DeepSeek API","Отдельный API-ключ и баланс; веб-аккаунт не подключается автоматически",()->open("https://api-docs.deepseek.com/"));
        options.addView(ui.text("Puter и Pollinations — отдельные агрегаторы. Готового входа в них в этой версии нет. Совместимый API своего сервиса можно настроить вручную; Gateway остаётся отдельной необязательной настройкой.",14,ui.theme.secondary));
        refresh();
    }
    // Reuse the same confirmation path after programmatically updating the switch.
    private void renderListener(){enabled.setOnCheckedChangeListener((v,on)->{if(!on){settings.preferences.edit().putBoolean("cloud_enabled",false).apply();refresh();}else{enabled.setChecked(false);confirm();}});}
    private void confirm(){try{JSONObject config=settings.readCloud();if(config==null){configure();return;}ui.dialog().setTitle("Включить облачный разговор?").setMessage("Сервис "+config.getString("endpoint")+" получит до 8 последних сообщений текущего чата, до 4000 символов каждое. Аудио не отправляется. Результаты Android-инструментов передаются только после отдельного разрешения в разделе «Мозг». Условия и лимиты определяет ваш аккаунт сервиса.").setNegativeButton("Отмена",null).setPositiveButton("Включить",(d,w)->{settings.preferences.edit().putBoolean("cloud_enabled",true).putBoolean("gateway_enabled",false).putBoolean("account_enabled",false).apply();enabled.setOnCheckedChangeListener(null);enabled.setChecked(true);renderListener();refresh();}).show();}catch(Exception error){configure();}}
    private void configure(){configure(null);}
    private void configure(String preset){
        LinearLayout form=ui.vertical();ui.padded(form,12);EditText endpoint=ui.field("HTTPS-адрес API с /v1"),model=ui.field("ID модели"),key=ui.field("Ключ API / токен вашего моста (если нужен)");
        endpoint.setSingleLine(true);model.setSingleLine(true);key.setSingleLine(true);key.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        try{JSONObject saved=settings.readCloud();if(preset!=null)endpoint.setText(preset);else if(saved!=null){endpoint.setText(saved.getString("endpoint"));model.setText(saved.getString("model"));key.setText(saved.optString("key"));}}catch(Exception ignored){}
        form.addView(ui.text("Совместимый Chat Completions API. Укажите ключ сервиса и нажмите «Получить модели». Если каталог не предоставляется, введите ID из документации. Веб-адрес chat.deepseek.com сюда не подходит.",14,ui.theme.secondary));
        form.addView(endpoint);form.addView(model);form.addView(key);
        form.addView(ui.button("Получить модели этого сервиса",()->{
            String address=endpoint.getText().toString().trim(),credential=key.getText().toString().trim();java.util.concurrent.ExecutorService worker=java.util.concurrent.Executors.newSingleThreadExecutor();worker.execute(()->{try{org.json.JSONArray catalog=DirectModelCatalog.models(address,credential);String[] labels=new String[catalog.length()];for(int i=0;i<labels.length;i++)labels[i]=catalog.getJSONObject(i).optString("name");activity.runOnUiThread(()->{if(activity.isDestroyed())return;if(!address.equals(endpoint.getText().toString().trim())||!credential.equals(key.getText().toString().trim())){endpoint.setError("Настройка изменилась. Получите каталог заново.");return;}ui.dialog().setTitle("Модели сервиса").setItems(labels,(d,index)->model.setText(catalog.optJSONObject(index).optString("id"))).setNegativeButton("Отмена",null).show();});}catch(Exception error){activity.runOnUiThread(()->{if(!activity.isDestroyed())endpoint.setError(error.getMessage()==null?"Не удалось прочитать каталог.":error.getMessage());});}finally{worker.shutdown();}});
        }));
        AlertDialog dialog=ui.dialog().setTitle("Облачное подключение").setView(form).setNegativeButton("Отмена",null).setNeutralButton("Удалить подключение",(d,w)->{settings.preferences.edit().remove("cloud_connection").putBoolean("cloud_enabled",false).apply();enabled.setChecked(false);refresh();}).setPositiveButton("Сохранить",null).show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{try{
            JSONObject value=new JSONObject().put("endpoint",endpoint.getText().toString().trim()).put("model",model.getText().toString().trim()).put("key",key.getText().toString().trim());CloudChat.validate(value);settings.saveCloud(value);enabled.setChecked(false);refresh();dialog.dismiss();
        }catch(Exception problem){endpoint.setError(problem.getMessage());}});
    }
    private void refresh(){try{JSONObject config=settings.readCloud();state.setText(config==null?"Облачный чат не настроен":(CloudChat.enabled(activity)?"Включён":"Выключен")+" · "+config.getString("model")+"\n"+config.getString("endpoint"));}catch(Exception problem){state.setText("Сохранённое подключение недоступно. Настройте его заново.");}}
    private void open(String url){try{activity.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)));}catch(Exception unavailable){Toast.makeText(activity,"Браузер не найден",Toast.LENGTH_SHORT).show();}}
}
