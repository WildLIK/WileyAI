package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.InsetDrawable;
import android.graphics.drawable.LayerDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.content.res.ColorStateList;
import android.os.Bundle;
import android.service.voice.VoiceInteractionSession;
import android.view.*;
import android.widget.*;
import java.util.List;

/** Small assistant surface; never consumes screenshots, assist structures or foreground app data. */
final class WileyVoiceSession extends VoiceInteractionSession implements HandsFreeService.Host {
    private final Context context; private final WileyTheme theme;
    private TextView status, heard, answer, subtitle; private NeonVoiceView wave,mark; private LinearLayout choices; private ScrollView messages; private boolean visible;
    WileyVoiceSession(Context context) { super(context); this.context = context; theme = WileyTheme.resolve(context, new SettingsRepository(context).theme()); }
    @Override public void onCreate() { super.onCreate(); setDisabledShowContext(SHOW_WITH_ASSIST | SHOW_WITH_SCREENSHOT); }
    private int dp(int n) { return Math.round(n * context.getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size, int color) { TextView text = new TextView(context); text.setText(value); text.setTextSize(size); text.setTextColor(color); text.setPadding(0, dp(5), 0, dp(5)); return text; }
    private Button button(String value, Runnable action) { Button button = new Button(context); button.setText(value); button.setAllCaps(false); button.setTextColor(theme.accentText); button.setMinHeight(dp(48)); GradientDrawable shape = new GradientDrawable(); shape.setColor(theme.high); shape.setCornerRadius(dp(14)); button.setBackground(shape); button.setOnClickListener(v -> action.run()); return button; }
    /** The existing button and action retain a 48 dp target; only the inset circle is drawn. */
    private Button voiceControl(boolean settings, Runnable action) {
        Button result = button("", action);
        result.setMinWidth(0); result.setMinimumWidth(0); result.setPadding(0, 0, 0, 0);
        GradientDrawable circle = new GradientDrawable();
        circle.setShape(GradientDrawable.OVAL); circle.setColor(0xdf20213b);
        circle.setStroke(dp(1), 0x408791dc);
        GradientDrawable mask = new GradientDrawable(); mask.setShape(GradientDrawable.OVAL); mask.setColor(0xffffffff);
        RippleDrawable ripple = new RippleDrawable(ColorStateList.valueOf(settings ? 0x6600dfff : 0x66874bff), circle, mask);
        Drawable icon = new VoiceControlIcon(settings);
        LayerDrawable layers = new LayerDrawable(new Drawable[]{new InsetDrawable(ripple, dp(3)), icon});
        layers.setLayerSize(1, dp(21), dp(21)); layers.setLayerGravity(1, Gravity.CENTER);
        result.setBackground(layers); result.setGravity(Gravity.CENTER);
        return result;
    }
    private final class VoiceControlIcon extends Drawable {
        private final boolean gear; private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG); private final Path path = new Path();
        VoiceControlIcon(boolean gear) { this.gear=gear; paint.setColor(0xffe9edff); paint.setStyle(Paint.Style.STROKE); paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND); }
        @Override public void draw(Canvas canvas) {
            android.graphics.Rect b=getBounds(); float cx=b.exactCenterX(), cy=b.exactCenterY(), size=Math.min(b.width(),b.height());
            paint.setStrokeWidth(size*(gear ? .075f : .085f));
            if (!gear) { float r=size*.30f; canvas.drawLine(cx-r,cy-r,cx+r,cy+r,paint); canvas.drawLine(cx+r,cy-r,cx-r,cy+r,paint); return; }
            path.reset();
            for(int i=0;i<32;i++){double angle=-Math.PI/2+i*Math.PI/16;float radius=size*((i%4==0||i%4==1)? .44f : .34f);float x=cx+(float)Math.cos(angle)*radius,y=cy+(float)Math.sin(angle)*radius;if(i==0)path.moveTo(x,y);else path.lineTo(x,y);}
            path.close(); canvas.drawPath(path,paint); canvas.drawCircle(cx,cy,size*.15f,paint);
        }
        @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); invalidateSelf(); }
        @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); invalidateSelf(); }
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    }
    @Override public View onCreateContentView() {
        FrameLayout root = new FrameLayout(context);
        root.setPadding(dp(12), dp(8), dp(12), dp(14));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            int bottom = insets.getSystemWindowInsetBottom();
            if (android.os.Build.VERSION.SDK_INT >= 30) bottom = Math.max(insets.getInsets(android.view.WindowInsets.Type.systemBars()).bottom, insets.getInsets(android.view.WindowInsets.Type.ime()).bottom);
            view.setPadding(dp(12), dp(8), dp(12), bottom + dp(14));
            return insets;
        });
        LinearLayout panel = new LinearLayout(context);panel.setOrientation(LinearLayout.VERTICAL);panel.setPadding(dp(14),dp(10),dp(14),dp(10));
        GradientDrawable shape=new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,new int[]{0xff101735,0xff080b18,0xff171039});shape.setCornerRadius(dp(30));shape.setStroke(dp(1),0xff6053be);panel.setBackground(shape);panel.setElevation(dp(8));
        FrameLayout.LayoutParams panelParams = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        root.addView(panel, panelParams);
        root.addOnLayoutChangeListener((v,left,top,right,bottom,oldLeft,oldTop,oldRight,oldBottom) -> {
            int width=Math.min(dp(600), Math.max(1,right-left-root.getPaddingLeft()-root.getPaddingRight()));
            FrameLayout.LayoutParams lp=(FrameLayout.LayoutParams)panel.getLayoutParams();
            if(lp.width!=width){lp.width=width;panel.setLayoutParams(lp);}
        });
        LinearLayout top=new LinearLayout(context);top.setGravity(Gravity.CENTER_VERTICAL);panel.addView(top);
        mark=new NeonVoiceView(context,true);top.addView(mark,new LinearLayout.LayoutParams(dp(52),dp(52)));
        LinearLayout labels=new LinearLayout(context);labels.setOrientation(LinearLayout.VERTICAL);labels.setPadding(dp(10),0,0,0);top.addView(labels,new LinearLayout.LayoutParams(0,-2,1));
        status=text("Готовлю микрофон…",16,0xfff2f5ff);status.setMaxLines(2);labels.addView(status);subtitle=text("",12,0xff929bb6);subtitle.setMaxLines(1);labels.addView(subtitle);
        Button settings=voiceControl(true,()->{startAssistantActivity(new Intent(context,MainActivity.class).setAction(HandsFreeService.SETTINGS));hide();});settings.setContentDescription("Настройки");top.addView(settings,new LinearLayout.LayoutParams(dp(48),dp(48)));
        Button cancel=voiceControl(false,this::hide);cancel.setContentDescription("Отмена");LinearLayout.LayoutParams cancelParams=new LinearLayout.LayoutParams(dp(48),dp(48));cancelParams.setMarginStart(dp(4));top.addView(cancel,cancelParams);
        wave=new NeonVoiceView(context,false);if(context.getResources().getConfiguration().screenWidthDp>=600)labels.addView(wave,new LinearLayout.LayoutParams(-1,dp(72)));else panel.addView(wave,new LinearLayout.LayoutParams(-1,dp(72)));
        android.content.SharedPreferences prefs=context.getSharedPreferences("wiley-mobile",0);int style=prefs.getInt("neon_intensity",2);boolean logoOn=prefs.getBoolean("neon_logo",true),reduce=prefs.getBoolean("neon_reduce",false);mark.configure(style,logoOn,reduce);wave.configure(style,logoOn,reduce);
        messages = new ScrollView(context) {
            @Override protected void onMeasure(int w, int h) {
                int available = android.view.View.MeasureSpec.getSize(h);
                int limit = Math.min(dp(200), available > 0 ? available : dp(200));
                super.onMeasure(w, android.view.View.MeasureSpec.makeMeasureSpec(limit, android.view.View.MeasureSpec.AT_MOST));
            }
        };
        messages.setFillViewport(false); messages.setVisibility(View.GONE);
        LinearLayout messageContent = new LinearLayout(context); messageContent.setOrientation(LinearLayout.VERTICAL); messages.addView(messageContent); panel.addView(messages);
        heard=text("",14,0xff929bb6);heard.setVisibility(View.GONE);messageContent.addView(heard);
        answer=text("",16,0xfff2f5ff);answer.setVisibility(View.GONE);messageContent.addView(answer);
        choices=new LinearLayout(context);choices.setOrientation(LinearLayout.VERTICAL);messageContent.addView(choices);return root;
    }
    @Override public void onShow(Bundle args, int flags) {
        super.onShow(args, flags); visible = true;DiagnosticLog.event(DiagnosticJournal.Event.VOICE_WINDOW_SHOW,0);
        var prefs=context.getSharedPreferences("wiley-mobile",0);int style=prefs.getInt("neon_intensity",2);boolean logoOn=prefs.getBoolean("neon_logo",true),reduce=prefs.getBoolean("neon_reduce",false);if(wave!=null)wave.configure(style,logoOn,reduce);if(mark!=null)mark.configure(style,logoOn,reduce);
        if(wave!=null)wave.paused(false);if(mark!=null)mark.paused(false);
        if (!HandsFreeService.answering() && choices != null) choices.removeAllViews();
        GigaAmRuntime.preloadIfSelected(context); // The first request must not wait for weights.
        if (getWindow() != null && getWindow().getWindow() != null) { Window window = getWindow().getWindow(); window.setBackgroundDrawableResource(android.R.color.transparent); window.setGravity(Gravity.BOTTOM); window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE); window.setLayout(-1, -2); window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED); }
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { show("Разрешите микрофон в настройках WileyAI", "", ""); return; }
        try { HandsFreeService.request(context, this,args!=null && args.getBoolean("conversation",false),
            args==null?0:args.getLong("wiley_wake_id")); } catch (RuntimeException denied) { show("Откройте WileyAI и включите голосовой режим в настройках", "", ""); }
    }
    @Override public void onHide() { DiagnosticLog.event(DiagnosticJournal.Event.VOICE_WINDOW_HIDE,0);visible = false;if(wave!=null)wave.paused(true);if(mark!=null)mark.paused(true); HandsFreeService.detached(this); super.onHide(); }
    @Override public void onDestroy() { visible = false; HandsFreeService.detached(this); super.onDestroy(); }
    @Override public boolean voiceOverlay(){return visible;}
    @Override public void show(String state,String transcript,String reply){
        if(!visible||status==null)return;status.setText(state);heard.setText(transcript);answer.setText(reply);
        heard.setVisibility(transcript == null || transcript.isEmpty() ? View.GONE : View.VISIBLE);
        answer.setVisibility(reply == null || reply.isEmpty() ? View.GONE : View.VISIBLE);
        updateMessages();
        String v=state.toLowerCase(java.util.Locale.ROOT);NeonVoiceView.Mode m;
        if(v.startsWith("говорите")||v.startsWith("слышу речь")){m=NeonVoiceView.Mode.LISTENING;subtitle.setText("Уровень микрофона");}
        else if(v.contains("распознаю")){m=NeonVoiceView.Mode.RECOGNIZING;subtitle.setText("Преобразую голос в текст");}
        else if(v.contains("ошиб")||v.contains("не удалось")){m=NeonVoiceView.Mode.ERROR;subtitle.setText("Попробуйте ещё раз");}
        else if(v.contains("отвечаю голосом")){m=NeonVoiceView.Mode.SPEAKING;subtitle.setText("Воспроизвожу ответ");}
        else if(v.contains("отвечаю")){m=NeonVoiceView.Mode.GENERATING;subtitle.setText("Готовлю ответ");}
        else if(v.contains("дума")||v.contains("обрабаты")||v.contains("выполня")||v.contains("ищу")||v.contains("модель")){m=NeonVoiceView.Mode.PROCESSING;subtitle.setText("Анализирую запрос");}
        else {m=NeonVoiceView.Mode.IDLE;subtitle.setText("");}DiagnosticLog.event(DiagnosticJournal.Event.VOICE_UI_STATE,m.ordinal());wave.state(m);mark.state(m);
    }
    private void updateMessages() { if (messages != null) messages.setVisibility(heard.getVisibility() == View.VISIBLE || answer.getVisibility() == View.VISIBLE || choices.getChildCount() > 0 ? View.VISIBLE : View.GONE); }
    @Override public void level(float value){if(visible&&wave!=null)wave.level(value);}
    @Override public void spectrum(float[] bands){if(visible&&wave!=null)wave.spectrum(bands);}
    @Override public void choices(List<AppRegistry.App> apps) { choices.removeAllViews(); for (int i = 0; i < apps.size(); i++) { AppRegistry.App app = apps.get(i); choices.addView(button((i + 1) + ". " + app.label(), () -> HandsFreeService.choose(app))); } updateMessages(); }
    @Override public void videos(List<YoutubeSearch.Video> videos) { choices.removeAllViews();for(int i=0;i<videos.size();i++){YoutubeSearch.Video video=videos.get(i);Button choice=button((i+1)+". "+video.title(),()->HandsFreeService.chooseVideo(video));choice.setMaxLines(2);choices.addView(choice);} updateMessages(); }
    @Override public void launch(Intent intent) { context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); hide(); }
    @Override public void confirm(String plan,java.util.function.Consumer<Boolean> reply){choices.removeAllViews();choices.addView(button("Выполнить",()->{choices.removeAllViews();reply.accept(true);}));choices.addView(button("Отмена",()->{choices.removeAllViews();reply.accept(false);}));updateMessages();}
    @Override public void dismiss() { hide(); }
}
