package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Isolated test-package screen with no user content and no side effects. */
public final class C9ExternalFixtureActivity extends Activity {
    @Override public void onCreate(Bundle state){super.onCreate(state);LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(32,32,32,32);
        TextView title=new TextView(this);title.setText("Безопасный экран проверки WileyAI");title.setTextSize(20);root.addView(title);
        Button first=new Button(this);first.setText("Звёздная карта");root.addView(first);
        Button second=new Button(this);second.setText("Лесная тропа");root.addView(second);
        setContentView(root);
    }
}
