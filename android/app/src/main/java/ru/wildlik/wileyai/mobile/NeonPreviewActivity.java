package ru.wildlik.wileyai.mobile;
import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
import android.view.View;
/** Synthetic preview; never connects to the microphone. */
public final class NeonPreviewActivity extends Activity {
 @Override public void onCreate(Bundle state){super.onCreate(state);LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(24,24,24,24);root.setBackgroundColor(0xff080b18);
  TextView title=new TextView(this);title.setText("Предпросмотр · синтетический сигнал");title.setTextColor(0xfff2f5ff);title.setTextSize(18);root.addView(title);
  NeonVoiceView logo=new NeonVoiceView(this,true);root.addView(logo,new LinearLayout.LayoutParams(-1,120));NeonVoiceView wave=new NeonVoiceView(this,false);root.addView(wave,new LinearLayout.LayoutParams(-1,200));
  var prefs=getSharedPreferences("wiley-mobile",0);int style=prefs.getInt("neon_intensity",2);boolean mark=prefs.getBoolean("neon_logo",true),reduced=prefs.getBoolean("neon_reduce",false);logo.configure(style,mark,reduced);wave.configure(style,mark,reduced);
  Spinner modes=new Spinner(this);String[] labels={"Ожидание","Слушаю","Распознавание","Обработка","Генерация","Ответ","Успех","Ошибка"};modes.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,labels));root.addView(modes);
  SeekBar level=new SeekBar(this);level.setMax(100);root.addView(level);modes.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){public void onNothingSelected(android.widget.AdapterView<?> a){} public void onItemSelected(android.widget.AdapterView<?> a,View v,int position,long id){var m=NeonVoiceView.Mode.values()[position];wave.state(m);logo.state(m);if(m==NeonVoiceView.Mode.LISTENING)wave.level(level.getProgress()/100f);}});
  level.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){public void onStartTrackingTouch(SeekBar b){}public void onStopTrackingTouch(SeekBar b){}public void onProgressChanged(SeekBar b,int n,boolean fromUser){wave.level(n/100f);}});Button done=new Button(this);done.setText("Закрыть");done.setOnClickListener(v->finish());root.addView(done);setContentView(root);
  Spinner widths=new Spinner(this);String[] sizes={"По ширине экрана","320 dp","360 dp","393 dp","430 dp","600 dp","800 dp"};widths.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,sizes));root.addView(widths,root.getChildCount()-1);widths.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){public void onNothingSelected(android.widget.AdapterView<?> a){}public void onItemSelected(android.widget.AdapterView<?> a,View v,int position,long id){int[] dp={0,320,360,393,430,600,800};int width=position==0?-1:Math.min(Math.round(dp[position]*getResources().getDisplayMetrics().density),getResources().getDisplayMetrics().widthPixels-48);wave.setLayoutParams(new LinearLayout.LayoutParams(width,200));}});
 }
}
