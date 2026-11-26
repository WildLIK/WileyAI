package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.app.AppOpsManager;
import android.content.Intent;
import android.provider.Settings;
import android.widget.LinearLayout;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Supplier;

final class PermissionPanel {
    private final Activity activity;
    private final MobileUi ui;
    private final RuntimeAccess access;
    private final List<Runnable> updates=new ArrayList<>();

    PermissionPanel(Activity activity,MobileUi ui,RuntimeAccess access){
        this.activity=activity;
        this.ui=ui;
        this.access=access;
    }

    void render(LinearLayout parent,Runnable screen,Runnable apps,Runnable cloud){
        for (RuntimeAccess.Item item : RuntimeAccess.Item.values()) {
            row(parent,item.title,item.description,()->access.status(item),()->access.request(item,ui,this::refresh));
        }
        row(parent,"Цифровой помощник","Вызов из Android",()->WileyVoiceService.selected(activity)?"Выбрана WileyAI":"WileyAI не выбрана",()->{
            try{activity.startActivity(new Intent(Settings.ACTION_VOICE_INPUT_SETTINGS));}
            catch(RuntimeException unavailable){system(new Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS));}
        });
        row(parent,"Статистика использования","Проверка запуска приложения",()->state(usageAllowed(activity)),
            ()->system(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)));
        row(parent,"Доступ к медиасессиям","Проверка управления плеером",()->state(PlayerControl.permitted(activity)),
            ()->system(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        row(parent,"Специальные возможности","Наблюдение за экраном по запросу",()->!ScreenObservationService.enabled(activity)?"Выключено в Android":
            ScreenObservationService.running()?"Служба подключена":"Ожидается подключение службы",screen);
        row(parent,"Приложения для наблюдения","Отдельные согласия",()->{
            var prefs=activity.getSharedPreferences("wiley-mobile",0);
            return "Сохранено согласий: "+prefs.getStringSet("screen_allowed_apps",java.util.Set.of()).size();
        },apps);
        ui.link(parent,"Инструменты и облако","Действия и передача результатов",cloud);
    }

    void refresh(){updates.forEach(Runnable::run);}

    private void row(LinearLayout parent,String title,String description,Supplier<String> status,Runnable action){
        var detail=ui.link(parent,title,description,action);
        Runnable update=()->{
            String label=status.get()+" · "+description;
            detail.setText(label);
            ((android.view.View)detail.getParent().getParent()).setContentDescription(title+". "+label);
        };
        updates.add(update);
        update.run();
    }

    static boolean usageAllowed(Activity activity){
        AppOpsManager ops=activity.getSystemService(AppOpsManager.class);
        return ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,android.os.Process.myUid(),activity.getPackageName())==AppOpsManager.MODE_ALLOWED;
    }

    private String state(boolean allowed){return allowed?"Разрешено":"Не разрешено";}
    private void system(Intent intent){
        try{activity.startActivity(intent);}
        catch(RuntimeException unavailable){ui.dialog().setMessage("Этот экран настроек Android недоступен.").setPositiveButton("Закрыть",null).show();}
    }
}
