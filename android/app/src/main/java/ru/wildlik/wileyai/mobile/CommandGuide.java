package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.widget.LinearLayout;
import java.util.function.Consumer;

final class CommandGuide {
    static void render(Activity activity,MobileUi ui,LinearLayout parent,boolean chatReady,boolean noteToolsReady,
                       Consumer<String> tryExample,Consumer<String> open){
        boolean screen=ScreenObservationService.enabled(activity)&&ScreenObservationService.running()
            &&activity.getSharedPreferences("wiley-mobile",0).getBoolean("screen_observation_enabled",false);
        boolean media=PlayerControl.permitted(activity);
        entry(ui,parent,"Приложения","Открой Телеграм на телефоне",
            "Открывает установленное приложение. Для текста дополнительный доступ не нужен.",true,tryExample,null);
        entry(ui,parent,"Музыка и видео","Следующая песня на телефоне",
            "Нужна активная медиасессия. Доступ к уведомлениям позволяет выбрать плеер и проверить результат."
                +(media?" Доступ выдан.":" Доступ не выдан, результат может быть недоступен."),
            true,tryExample,()->open.accept("permissions"));
        entry(ui,parent,"Экран","Что на экране?",
            "Наблюдает структуру текущего окна по запросу. Для сторонних приложений нужно отдельное согласие. Защищённые окна недоступны.",
            screen,tryExample,()->open.accept("screen"));
        entry(ui,parent,"Память","Что ты обо мне помнишь?",
            "Показывает сохранённые записи на телефоне. Сохранение и удаление требуют подтверждения.",
            true,tryExample,()->open.accept("memory"));
        entry(ui,parent,"Общение","Почему меняются времена года?",
            "Обычный вопрос к выбранному источнику чата. Системные разрешения для текста не нужны.",
            chatReady,tryExample,()->open.accept("neural"));
        entry(ui,parent,"Устройства","Уровень заряда на телефоне",
            "Показывает заряд этого телефона. Дополнительный доступ не нужен.",true,tryExample,null);
        entry(ui,parent,"Заметки и напоминания","Сохрани заметку: купить чай",
            "Создаёт локальную заметку после подтверждения плана модели. Нужны выбранный источник телефона и доступ к инструментам. Заметки и задачи ПК открываются в разделе записей.",
            noteToolsReady,tryExample,()->open.accept("notes"));
        parent.addView(ui.text("Для произнесения примеров в голосовом режиме нужен доступ к микрофону.",14,ui.theme.secondary));
    }

    private static void entry(MobileUi ui,LinearLayout parent,String title,String command,String detail,
                              boolean ready,Consumer<String> example,Runnable setup){
        LinearLayout section=ui.disclosure(parent,title);
        ui.card(section,command,(ready?"Поддерживается":"Требуется настройка")+"\n"+detail);
        section.addView(ui.button("Попробовать",()->example.accept(command)));
        if(setup!=null)section.addView(ui.button("Настроить",setup));
    }

    private static void unavailable(MobileUi ui,LinearLayout parent,String title,String detail,Runnable manage){
        LinearLayout section=ui.disclosure(parent,title);
        section.addView(ui.text(detail,14,ui.theme.text));
        section.addView(ui.button("Открыть раздел",manage));
    }

    private CommandGuide(){}
}
