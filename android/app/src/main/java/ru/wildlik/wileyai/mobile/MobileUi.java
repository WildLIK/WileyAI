package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.content.res.ColorStateList;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Small native design system. Static backgrounds work with reduced motion and low RAM. */
final class MobileUi {
    private final Activity activity;
    private final android.content.Context themed;
    final WileyTheme theme;
    private final Typeface onest;
    private ArtThemeView artView;
    MobileUi(Activity activity, String selected) { this.activity = activity; theme = WileyTheme.resolve(activity, selected); themed = new android.view.ContextThemeWrapper(activity, theme.dialogStyle); Typeface face;try{face=Typeface.createFromAsset(activity.getAssets(),"fonts/Onest.ttf");}catch(RuntimeException ignored){face=Typeface.create("sans-serif",Typeface.NORMAL);}onest=face; }
    Typeface font(int weight) {return android.os.Build.VERSION.SDK_INT>=28?Typeface.create(onest,weight,false):Typeface.create(onest,weight>=600?Typeface.BOLD:Typeface.NORMAL);}
    void typography(TextView v,int weight){v.setTypeface(font(weight));}
    android.app.AlertDialog.Builder dialog() { return new WileyDialogs(activity, this); }
    int dp(float value) { return Math.round(value * activity.getResources().getDisplayMetrics().density); }
    GradientDrawable panel(int color, int radius) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color); shape.setCornerRadius(dp(radius));
        shape.setStroke(dp(1), theme.border); return shape;
    }
    private GradientDrawable surface(int color,int radius,boolean focused) {
        GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));
        if(focused)d.setStroke(dp(2),theme.accent);return d;
    }
    android.graphics.drawable.Drawable interactive(int normal,int selected,int radius) {
        StateListDrawable states=new StateListDrawable();
        states.addState(new int[]{-android.R.attr.state_enabled},surface(theme.base,radius,false));
        states.addState(new int[]{android.R.attr.state_focused},surface(selected,radius,true));
        states.addState(new int[]{android.R.attr.state_selected},surface(selected,radius,false));
        states.addState(new int[]{},surface(normal,radius,false));
        GradientDrawable mask=surface(android.graphics.Color.WHITE,radius,false);
        return new RippleDrawable(ColorStateList.valueOf((theme.accent & 0x00ffffff) | 0x55000000),states,mask);
    }
    void controlIcon(Button view,int resource) {
        android.graphics.drawable.Drawable glyph=activity.getDrawable(resource).mutate();glyph.setTint(theme.text);
        android.graphics.drawable.Drawable background=view.getBackground();
        android.graphics.drawable.LayerDrawable layer;
        if(background instanceof android.graphics.drawable.LayerDrawable && !(background instanceof RippleDrawable)) {
            layer=(android.graphics.drawable.LayerDrawable)background; layer.setDrawable(1,glyph);
        } else {
            layer=new android.graphics.drawable.LayerDrawable(new android.graphics.drawable.Drawable[]{background,glyph});
            layer.setLayerGravity(1,Gravity.CENTER);layer.setLayerSize(1,dp(22),dp(22));view.setBackground(layer);
        }
        view.setText("");
    }
    LinearLayout vertical() { LinearLayout layout = new LinearLayout(activity); layout.setOrientation(LinearLayout.VERTICAL); return layout; }
    LinearLayout row() { LinearLayout layout = new LinearLayout(activity); layout.setGravity(Gravity.CENTER_VERTICAL); return layout; }
    TextView text(String value, int size, int color) {
        TextView view = new TextView(themed); view.setText(value); view.setTextSize(size); view.setTextColor(color); typography(view,size>=20?600:400); view.setLineSpacing(dp(2), 1.08f); return view;
    }
    Button button(String value, Runnable action) {
        Button view = new Button(themed); view.setText(value); view.setAllCaps(false); view.setTextSize(14); typography(view,500);
        styleAction(view);
        view.setPadding(dp(8), dp(4), dp(8), dp(4)); view.setOnClickListener(v -> action.run());
        return view;
    }
    void styleAction(Button view) {
        view.setAllCaps(false);
        typography(view,500);
        view.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},new int[]{theme.muted,theme.text}));
        view.setMinHeight(dp(48));
        view.setMinimumHeight(dp(48));
        android.graphics.drawable.Drawable body = interactive(theme.mid,theme.high,12);
        view.setBackground(new android.graphics.drawable.InsetDrawable(body,dp(3),dp(3),dp(3),dp(3)));
    }
    void styleControl(android.widget.Switch control) {
        typography(control,500);
        control.setTextColor(theme.text);
        control.setTextSize(14);
        control.setMinHeight(dp(48));
        control.setPadding(dp(10),dp(4),dp(10),dp(4));
        control.setBackground(new android.graphics.drawable.InsetDrawable(interactive(theme.low,theme.high,12),0,dp(3),0,dp(3)));
        control.setThumbTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked},new int[]{}},new int[]{theme.accent,theme.secondary}));
        control.setTrackTintList(ColorStateList.valueOf(theme.border));
    }
    android.widget.Switch setting(LinearLayout parent,String label,boolean initial,java.util.function.Consumer<Boolean> changed) {
        android.widget.Switch control=new android.widget.Switch(themed);
        control.setText(label);
        styleControl(control);
        control.setChecked(initial);
        control.setOnCheckedChangeListener((v,on)->changed.accept(on));
        parent.addView(control,new LinearLayout.LayoutParams(-1,-2));
        return control;
    }
    Button roundControl(String value, Runnable action) {
        Button view=button(value,action); view.setMinWidth(0);view.setMinimumWidth(0);view.setPadding(0,0,0,0);view.setTextSize(20);
        view.setBackground(interactive(theme.mid,theme.high,100));return view;
    }
    private int blend(int a,int b,float t) {return android.graphics.Color.rgb((int)(android.graphics.Color.red(a)*(1-t)+android.graphics.Color.red(b)*t),(int)(android.graphics.Color.green(a)*(1-t)+android.graphics.Color.green(b)*t),(int)(android.graphics.Color.blue(a)*(1-t)+android.graphics.Color.blue(b)*t));}
    GradientDrawable bubble(int color){GradientDrawable d=panel(color,16);d.setStroke(dp(.7f),blend(theme.border,color,.35f));return d;}
    private android.graphics.drawable.Drawable background() {
        if(theme.base!=android.graphics.Color.parseColor("#080f1c")&&theme.base!=android.graphics.Color.parseColor("#07060d"))return new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{theme.mid,theme.base,theme.low});
        boolean nebula=theme.base==android.graphics.Color.parseColor("#07060d");
        GradientDrawable base=new GradientDrawable(GradientDrawable.Orientation.TL_BR,nebula?new int[]{0xff15112b,0xff0c1020,0xff080710,0xff100b1b}:new int[]{0xff11203b,0xff11152e,0xff0a1022,0xff0a0816});
        GradientDrawable cyan=new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,new int[]{0x2252dcea,0x00000000});cyan.setGradientType(GradientDrawable.RADIAL_GRADIENT);cyan.setGradientCenter(.08f,.02f);cyan.setGradientRadius(dp(260));
        GradientDrawable violet=new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,new int[]{0x255e3dce,0x00000000});violet.setGradientType(GradientDrawable.RADIAL_GRADIENT);violet.setGradientCenter(.94f,.14f);violet.setGradientRadius(dp(300));
        return new android.graphics.drawable.LayerDrawable(new android.graphics.drawable.Drawable[]{base,cyan,violet});
    }
    void focusField(EditText view) {
        GradientDrawable normal=panel(theme.low,16), focused=panel(theme.low,16);normal.setStroke(dp(1),blend(theme.border,theme.secondary,.20f));focused.setStroke(dp(1.5f),theme.accent);
        StateListDrawable states=new StateListDrawable();states.addState(new int[]{android.R.attr.state_focused},focused);states.addState(new int[]{},normal);view.setBackground(states);
    }
    void headerControl(Button button) {
        StateListDrawable states=new StateListDrawable();
        GradientDrawable normal=surface(theme.low,14,false);normal.setStroke(dp(1),blend(theme.border,theme.accent,.52f));
        GradientDrawable selected=surface(theme.high,14,false);selected.setStroke(dp(1.5f),theme.accent);
        states.addState(new int[]{android.R.attr.state_focused},selected);
        states.addState(new int[]{android.R.attr.state_selected},selected);
        states.addState(new int[]{},normal);
        button.setBackground(new RippleDrawable(ColorStateList.valueOf((theme.accent & 0x00ffffff)|0x66000000),states,surface(android.graphics.Color.WHITE,14,false)));
    }
    void navigationItem(Button button,boolean active) {
        button.setBackground(interactive(android.graphics.Color.TRANSPARENT,theme.high,14));button.setTextColor(active?theme.accentText:theme.secondary);
    }
    EditText field(String hint) {
        EditText view = new EditText(themed); view.setHint(hint); view.setHintTextColor(theme.muted);
        view.setTextColor(theme.text); view.setTextSize(16); typography(view,400); view.setMinHeight(dp(52));
        view.setPadding(dp(14), dp(12), dp(14), dp(12)); focusField(view); return view;
    }
    void padded(View view, int top) { view.setPadding(dp(16), dp(top), dp(16), dp(8)); }
    LinearLayout root() {
        activity.getWindow().setStatusBarColor(theme.base); activity.getWindow().setNavigationBarColor(theme.base);
        boolean light = theme.text == android.graphics.Color.parseColor("#142f49");
        activity.getWindow().getDecorView().setSystemUiVisibility(light ? View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR : 0);
        android.widget.FrameLayout frame=new android.widget.FrameLayout(activity);frame.setBackground(background());
        android.content.SharedPreferences prefs=activity.getSharedPreferences("wiley-mobile",android.content.Context.MODE_PRIVATE);
        if(prefs.getBoolean("art_background",true)){
            String kind=theme.base==android.graphics.Color.parseColor("#e6f1fa")?"ice":theme.base==android.graphics.Color.parseColor("#0b0b10")?"ember":theme.base==android.graphics.Color.parseColor("#07060d")?"nebula":"aurora";
            artView=new ArtThemeView(activity,kind,prefs.getBoolean("art_animation",true),theme.base,()->activity instanceof MainActivity && ((MainActivity)activity).artModelBusy());
            frame.addView(artView,new android.widget.FrameLayout.LayoutParams(-1,-1));
        }else artView=null;
        LinearLayout root=vertical();frame.addView(root,new android.widget.FrameLayout.LayoutParams(-1,-1));activity.setContentView(frame);return root;
    }
    void pauseArt(boolean paused){if(artView!=null)artView.paused(paused);}
    void card(LinearLayout parent, String title, String description) {
        LinearLayout card = vertical(); card.setPadding(dp(16), dp(14), dp(16), dp(14)); card.setBackground(panel(theme.low, 18));
        TextView heading = text(title, 18, theme.accentText); typography(heading,600); card.addView(heading);
        TextView detail = text(description, 15, theme.secondary); detail.setPadding(0, dp(8), 0, 0); detail.setTextIsSelectable(true); card.addView(detail);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(8), 0, dp(8)); parent.addView(card, params);
    }
    TextView link(LinearLayout parent,String title,String subtitle,Runnable action) {return link(parent,title,subtitle,action,0);}
    TextView link(LinearLayout parent, String title, String subtitle, Runnable action,int iconResource) {
        LinearLayout card = row(); card.setPadding(dp(10), dp(5), dp(10), dp(5)); card.setBackground(interactive(theme.low,theme.high,12)); card.setMinimumHeight(dp(48));
        if(iconResource!=0){android.widget.ImageView icon=new android.widget.ImageView(activity);icon.setImageResource(iconResource);icon.setColorFilter(theme.accentText);LinearLayout.LayoutParams ip=new LinearLayout.LayoutParams(dp(22),dp(22));ip.setMargins(0,0,dp(12),0);card.addView(icon,ip);}
        LinearLayout labels = vertical(); TextView heading = text(title, 15, theme.text); typography(heading,600); labels.addView(heading);
        TextView detail = text(subtitle, 12, theme.secondary); detail.setPadding(0, dp(1), 0, 0); labels.addView(detail);
        card.addView(labels, new LinearLayout.LayoutParams(0, -2, 1)); android.widget.ImageView arrow=new android.widget.ImageView(activity);arrow.setImageResource(R.drawable.ui_chevron);arrow.setColorFilter(theme.secondary);card.addView(arrow,new LinearLayout.LayoutParams(dp(20),dp(20)));
        card.setOnClickListener(v -> action.run()); card.setFocusable(true); card.setContentDescription(title + ". " + subtitle);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(3), 0, dp(3)); parent.addView(card, params);
        return detail;
    }
    LinearLayout disclosure(LinearLayout parent, String title) {
        LinearLayout content = vertical(); content.setVisibility(View.GONE);
        Button toggle = button(title, () -> {});toggle.setGravity(Gravity.CENTER_VERTICAL|Gravity.START);toggle.setTextSize(16);toggle.setBackground(interactive(android.graphics.Color.TRANSPARENT,theme.high,10));
        android.graphics.drawable.Drawable arrow=activity.getDrawable(R.drawable.ui_chevron).mutate();arrow.setTint(theme.secondary);arrow.setBounds(0,0,dp(20),dp(20));toggle.setCompoundDrawables(null,null,arrow,null);
        toggle.setOnClickListener(v -> {boolean open=content.getVisibility()!=View.VISIBLE;content.setVisibility(open?View.VISIBLE:View.GONE);toggle.setSelected(open);toggle.setContentDescription(title+(open?", раскрыто":", свёрнуто"));});
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(8), 0, dp(4)); parent.addView(toggle, params); parent.addView(content); return content;
    }
}
