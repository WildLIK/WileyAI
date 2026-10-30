package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.service.voice.VoiceInteractionSession;
import android.view.*;
import android.widget.*;
import java.util.List;

/** Small assistant surface; never consumes screenshots, assist structures or foreground app data. */
final class WileyVoiceSession extends VoiceInteractionSession implements HandsFreeService.Host {
    private final Context context; private final WileyTheme theme;
    private TextView status, heard, answer; private LinearLayout choices; private boolean visible;
    WileyVoiceSession(Context context) { super(context); this.context = context; theme = WileyTheme.resolve(context, new SettingsRepository(context).theme()); }
    @Override public void onCreate() { super.onCreate(); setDisabledShowContext(SHOW_WITH_ASSIST | SHOW_WITH_SCREENSHOT); }
    private int dp(int n) { return Math.round(n * context.getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size, int color) { TextView text = new TextView(context); text.setText(value); text.setTextSize(size); text.setTextColor(color); text.setPadding(0, dp(5), 0, dp(5)); return text; }
    private Button button(String value, Runnable action) { Button button = new Button(context); button.setText(value); button.setAllCaps(false); button.setTextColor(theme.accentText); button.setMinHeight(dp(48)); GradientDrawable shape = new GradientDrawable(); shape.setColor(theme.high); shape.setCornerRadius(dp(14)); button.setBackground(shape); button.setOnClickListener(v -> action.run()); return button; }
    @Override public View onCreateContentView() {
        LinearLayout panel = new LinearLayout(context); panel.setOrientation(LinearLayout.VERTICAL); panel.setPadding(dp(20), dp(16), dp(20), dp(18));
        GradientDrawable shape = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{theme.mid, theme.low}); shape.setCornerRadius(dp(24)); shape.setStroke(dp(1), theme.border); panel.setBackground(shape);
        panel.addView(text("Уайли", 24, theme.text)); status = text("Готовлю микрофон…", 16, theme.accentText); panel.addView(status);
        heard = text("", 16, theme.secondary); panel.addView(heard); answer = text("", 17, theme.text); answer.setMaxLines(8); panel.addView(answer);
        choices = new LinearLayout(context); choices.setOrientation(LinearLayout.VERTICAL); panel.addView(choices);
        LinearLayout row = new LinearLayout(context); row.addView(button("Настройки", () -> { startAssistantActivity(new Intent(context, MainActivity.class).setAction(HandsFreeService.SETTINGS)); hide(); }), new LinearLayout.LayoutParams(0, -2, 1)); row.addView(button("Закрыть", this::hide), new LinearLayout.LayoutParams(0, -2, 1)); panel.addView(row);
        return panel;
    }
    @Override public void onShow(Bundle args, int flags) {
        super.onShow(args, flags); visible = true;
        if (!HandsFreeService.answering() && choices != null) choices.removeAllViews();
        if (getWindow() != null && getWindow().getWindow() != null) { Window window = getWindow().getWindow(); window.setBackgroundDrawableResource(android.R.color.transparent); window.setGravity(Gravity.BOTTOM); window.setLayout(-1, -2); window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED); }
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { show("Разрешите микрофон в настройках WileyAI", "", ""); return; }
        try { HandsFreeService.request(context, this,args!=null && args.getBoolean("conversation",false)); } catch (RuntimeException denied) { show("Откройте WileyAI и включите голосовой режим в настройках", "", ""); }
    }
    @Override public void onHide() { visible = false; HandsFreeService.detached(this); super.onHide(); }
    @Override public void onDestroy() { visible = false; HandsFreeService.detached(this); super.onDestroy(); }
    @Override public void show(String state, String transcript, String reply) { if (!visible || status == null) return; status.setText(state); heard.setText(transcript); answer.setText(reply); }
    @Override public void choices(List<AppRegistry.App> apps) { choices.removeAllViews(); for (int i = 0; i < apps.size(); i++) { AppRegistry.App app = apps.get(i); choices.addView(button((i + 1) + ". " + app.label(), () -> HandsFreeService.choose(app))); } }
    @Override public void videos(List<YoutubeSearch.Video> videos) { choices.removeAllViews();for(int i=0;i<videos.size();i++){YoutubeSearch.Video video=videos.get(i);Button choice=button((i+1)+". "+video.title(),()->HandsFreeService.chooseVideo(video));choice.setMaxLines(2);choices.addView(choice);} }
    @Override public void launch(Intent intent) { context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); hide(); }
    @Override public void confirm(String plan,java.util.function.Consumer<Boolean> reply){choices.removeAllViews();choices.addView(button("Выполнить",()->{choices.removeAllViews();reply.accept(true);}));choices.addView(button("Отмена",()->{choices.removeAllViews();reply.accept(false);}));}
    @Override public void dismiss() { hide(); }
}
