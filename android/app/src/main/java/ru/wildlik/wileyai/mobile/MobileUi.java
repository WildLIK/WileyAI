package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
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
    MobileUi(Activity activity, String selected) { this.activity = activity; theme = WileyTheme.resolve(activity, selected); themed = new android.view.ContextThemeWrapper(activity, theme.dialogStyle); }
    android.app.AlertDialog.Builder dialog() { return new WileyDialogs(activity, this); }
    int dp(float value) { return Math.round(value * activity.getResources().getDisplayMetrics().density); }
    GradientDrawable panel(int color, int radius) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color); shape.setCornerRadius(dp(radius));
        shape.setStroke(dp(1), theme.border); return shape;
    }
    LinearLayout vertical() { LinearLayout layout = new LinearLayout(activity); layout.setOrientation(LinearLayout.VERTICAL); return layout; }
    LinearLayout row() { LinearLayout layout = new LinearLayout(activity); layout.setGravity(Gravity.CENTER_VERTICAL); return layout; }
    TextView text(String value, int size, int color) {
        TextView view = new TextView(themed); view.setText(value); view.setTextSize(size); view.setTextColor(color); view.setLineSpacing(dp(3), 1); return view;
    }
    Button button(String value, Runnable action) {
        Button view = new Button(themed); view.setText(value); view.setAllCaps(false); view.setTextSize(13);
        view.setTextColor(theme.text); view.setBackground(panel(theme.mid, 14)); view.setMinHeight(dp(48));
        view.setPadding(dp(8), dp(4), dp(8), dp(4)); view.setOnClickListener(v -> action.run());
        return view;
    }
    EditText field(String hint) {
        EditText view = new EditText(themed); view.setHint(hint); view.setHintTextColor(theme.muted);
        view.setTextColor(theme.text); view.setTextSize(16); view.setMinHeight(dp(52));
        view.setPadding(dp(14), dp(12), dp(14), dp(12)); view.setBackground(panel(theme.low, 16)); return view;
    }
    void padded(View view, int top) { view.setPadding(dp(16), dp(top), dp(16), dp(8)); }
    LinearLayout root() {
        activity.getWindow().setStatusBarColor(theme.base); activity.getWindow().setNavigationBarColor(theme.base);
        boolean light = theme.text == android.graphics.Color.parseColor("#142f49");
        activity.getWindow().getDecorView().setSystemUiVisibility(light ? View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR : 0);
        LinearLayout root = vertical();
        root.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{theme.mid, theme.base, theme.low}));
        activity.setContentView(root); return root;
    }
    void card(LinearLayout parent, String title, String description) {
        LinearLayout card = vertical(); card.setPadding(dp(16), dp(14), dp(16), dp(14)); card.setBackground(panel(theme.low, 18));
        TextView heading = text(title, 18, theme.accentText); heading.setTypeface(null, Typeface.BOLD); card.addView(heading);
        TextView detail = text(description, 15, theme.secondary); detail.setPadding(0, dp(8), 0, 0); detail.setTextIsSelectable(true); card.addView(detail);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(8), 0, dp(8)); parent.addView(card, params);
    }
    TextView link(LinearLayout parent, String title, String subtitle, Runnable action) {
        LinearLayout card = row(); card.setPadding(dp(16), dp(14), dp(12), dp(14)); card.setBackground(panel(theme.low, 18)); card.setMinimumHeight(dp(76));
        LinearLayout labels = vertical(); TextView heading = text(title, 18, theme.text); heading.setTypeface(null, Typeface.BOLD); labels.addView(heading);
        TextView detail = text(subtitle, 14, theme.secondary); detail.setPadding(0, dp(4), 0, 0); labels.addView(detail);
        card.addView(labels, new LinearLayout.LayoutParams(0, -2, 1)); card.addView(text("›", 28, theme.accentText));
        card.setOnClickListener(v -> action.run()); card.setFocusable(true); card.setContentDescription(title + ". " + subtitle);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(6), 0, dp(6)); parent.addView(card, params);
        return detail;
    }
    LinearLayout disclosure(LinearLayout parent, String title) {
        LinearLayout content = vertical(); content.setVisibility(View.GONE);
        Button toggle = button(title + "  ▸", () -> {});
        toggle.setOnClickListener(v -> { boolean open = content.getVisibility() != View.VISIBLE; content.setVisibility(open ? View.VISIBLE : View.GONE); toggle.setText(title + (open ? "  ▾" : "  ▸")); });
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(8), 0, dp(4)); parent.addView(toggle, params); parent.addView(content); return content;
    }
}
