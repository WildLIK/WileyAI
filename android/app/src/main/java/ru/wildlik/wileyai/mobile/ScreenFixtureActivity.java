package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.*;

/** User-operated, fixed-content screen for testing the read-only service. */
public final class ScreenFixtureActivity extends Activity {
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        MobileUi ui=new MobileUi(this,new SettingsRepository(this).theme());LinearLayout view=ui.root();ui.padded(view,12);
        view.addView(ui.text("Безопасный тест наблюдения",20,ui.theme.accentText));
        view.addView(ui.text("Здесь нет личных данных. Нажатия ниже управляют только этим тестовым экраном.",14,ui.theme.secondary));
        view.addView(ui.button("Поиск",()->{}));view.addView(ui.button("Тестовая кнопка",()->{}));
        EditText field=ui.field("Поле поиска");view.addView(field);
        TextView result=ui.text("Результат проверки появится здесь.",15,ui.theme.text);view.addView(result);
        view.addView(ui.button("Проверить текущий экран",()->view.postDelayed(()->ScreenDispatcher.dispatch(this,null,"опиши экран",()->!isFinishing()&&!isDestroyed(),result::setText),300)));
        view.addView(ui.button("Найти кнопку поиска",()->view.postDelayed(()->ScreenDispatcher.dispatch(this,null,"найди кнопку поиска",()->!isFinishing()&&!isDestroyed(),result::setText),300)));
        EditText password=ui.field("Тестовое защищённое поле");password.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);password.setVisibility(View.GONE);view.addView(password);
        view.addView(ui.button("Показать защищённое поле",()->password.setVisibility(View.VISIBLE)));
        view.addView(ui.button("Закрыть",this::finish));setContentView(view);
    }
}
