package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.*;
import android.os.*;
import android.provider.Settings;
import android.widget.*;
import java.util.function.BooleanSupplier;

final class MediaPanel {
    static final String SETTINGS="wiley.assistant.MEDIA_SETTINGS";
    private final Activity activity; private final MobileUi ui; private final AppCatalog catalog; private final BooleanSupplier foreground;
    private final Handler main=new Handler(Looper.getMainLooper()); private boolean closed; private String target="music"; private TextView access,result; private Button music,video;
    private final Runnable poll=new Runnable(){ public void run(){ if(closed)return; if(foreground.getAsBoolean())refresh(); main.postDelayed(this,2000); } };
    MediaPanel(Activity activity,MobileUi ui,AppCatalog catalog,BooleanSupplier foreground){this.activity=activity;this.ui=ui;this.catalog=catalog;this.foreground=foreground;}
    void render(LinearLayout parent){
        access=ui.text("",15,ui.theme.accentText);parent.addView(access);
        parent.addView(ui.button("Подключить управление плеерами",this::permission));
        music=ui.button("Музыка: "+catalog.preferredLabel("music"),()->choose("music"));parent.addView(music);
        video=ui.button("YouTube: "+catalog.preferredLabel("video"),()->choose("video"));parent.addView(video);
        LinearLayout tabs=ui.row();tabs.addView(ui.button("Управлять музыкой",()->{target="music";refresh();}),new LinearLayout.LayoutParams(0,-2,1));tabs.addView(ui.button("Управлять YouTube",()->{target="youtube";refresh();}),new LinearLayout.LayoutParams(0,-2,1));parent.addView(tabs);
        result=ui.text("Выберите плеер и команду",16,ui.theme.text);result.setMaxLines(5);parent.addView(result);
        row(parent,"Пауза","pause","Продолжить","play");row(parent,"Предыдущий","previous","Следующий","next");row(parent,"−30 секунд","seek:-30000","+30 секунд","seek:30000");
        parent.addView(ui.button("Что сейчас играет?",()->command("status")));
        EditText query=ui.field("Название песни, исполнителя или видео");query.setSingleLine(true);parent.addView(query);
        query.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH);
        query.setOnEditorActionListener((v,action,event)->{if(action!=android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH)return false;String value=query.getText().toString().trim();if(value.isEmpty()||value.length()>200){query.setError("Введите запрос до 200 символов");return true;}new PhoneActionEngine(activity,text->{if(!closed)result.setText(text);},catalog,foreground).execute(new PhoneCommands.Action("media_search",value,target));return true;});
        LinearLayout search=ui.row();for(String kind:new String[]{"media_search","media_play_search"})search.addView(ui.button(kind.equals("media_search")?"Найти":"Включить",()->{
            String value=query.getText().toString().trim();if(value.isEmpty()||value.length()>200){query.setError("Введите запрос до 200 символов");return;}
            new PhoneActionEngine(activity,text->{if(!closed)result.setText(text);},catalog,foreground).execute(new PhoneCommands.Action(kind,value,target));
        }),new LinearLayout.LayoutParams(0,-2,1));parent.addView(search);
        LinearLayout help=ui.disclosure(parent,"Голосовые команды и доступ Android");
        Switch autoplay=new Switch(activity);autoplay.setText("Сразу включать первое найденное видео");autoplay.setTextColor(ui.theme.text);autoplay.setMinHeight(ui.dp(56));android.content.SharedPreferences preferences=activity.getSharedPreferences("wiley-mobile",0);autoplay.setChecked(preferences.getBoolean("youtube_first_result",false));autoplay.setOnCheckedChangeListener((v,on)->preferences.edit().putBoolean("youtube_first_result",on).apply());parent.addView(autoplay);
        parent.addView(ui.text("«Включи видео … на Ютуб» предлагает найденные ролики: скажите «да» или номер. Автозапуск выше пропускает выбор. Если публичный поиск недоступен, откроется поиск самого YouTube.",14,ui.theme.secondary));
        help.addView(ui.text("«Пауза в Ютубе», «продолжи музыку», «следующее видео», «перемотай видео вперёд на тридцать секунд», «перемотай на 2:30 в Ютубе», «какая песня играет», «найди песню Вальс цветов», «найди видео про космос». Управление зависит от команд, которые предоставляет плеер.",14,ui.theme.secondary));
        help.addView(ui.text("Android открывает доступ к медиасессиям через разрешение доступа к уведомлениям. WileyAI не читает тексты уведомлений: их доставка отключена, обработчиков содержимого нет. Из медиасессий используются только выбранные плееры. Доступ можно отозвать той же кнопкой настройки.",14,ui.theme.secondary));refresh();main.postDelayed(poll,2000);
    }
    private void row(LinearLayout parent,String a,String first,String b,String second){LinearLayout row=ui.row();row.addView(ui.button(a,()->command(first)),new LinearLayout.LayoutParams(0,-2,1));row.addView(ui.button(b,()->command(second)),new LinearLayout.LayoutParams(0,-2,1));parent.addView(row);}
    private void command(String verb){result.setText("Проверяю результат…");PlayerControl.execute(activity,new PhoneCommands.Action("media",verb,target),text->{if(!closed)result.setText(text);});}
    private void choose(String role){new AppCatalogPanel(activity,ui,catalog,foreground).chooseRole(role,this::refresh);}
    private static void text(TextView view,String value){if(!view.getText().toString().equals(value))view.setText(value);}
    void refresh(){if(closed||access==null)return;text(access,(PlayerControl.permitted(activity)?"Управление медиасессиями подключено":"Управление медиасессиями не подключено")+"\nВыбрано: "+(target.equals("youtube")?"YouTube":"музыка"));text(music,"Музыка: "+catalog.preferredLabel("music"));text(video,"YouTube: "+catalog.preferredLabel("video"));}
    private void permission(){ui.dialog().setTitle("Управление музыкой и YouTube").setMessage("Для выбора конкретного плеера, перемотки и проверки результата Android требует доступ к медиасессиям через «Доступ к уведомлениям». WileyAI не читает и не сохраняет содержимое уведомлений. Используются только состояния выбранных плееров. Разрешение включается и отзывается в системных настройках.").setNegativeButton("Отмена",null).setPositiveButton("Настройки Android",(d,w)->{
        try{Intent intent=new Intent(Build.VERSION.SDK_INT>=30?Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS:Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS);if(Build.VERSION.SDK_INT>=30)intent.putExtra(Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME,PlayerControl.listener(activity).flattenToString());activity.startActivity(intent);}catch(RuntimeException unsupported){activity.startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));}
    }).show();}
    void close(){closed=true;main.removeCallbacks(poll);}
}
