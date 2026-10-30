package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.view.ContextThemeWrapper;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.TextView;

/** All modal surfaces share the currently selected WileyAI palette. */
final class WileyDialogs extends AlertDialog.Builder {
    private final Activity activity;
    private final MobileUi ui;
    WileyDialogs(Activity activity, MobileUi ui) {
        super(new ContextThemeWrapper(activity, ui.theme.dialogStyle));
        this.activity = activity; this.ui = ui;
    }
    @Override public AlertDialog.Builder setItems(CharSequence[] items, DialogInterface.OnClickListener listener) {
        return super.setAdapter(new ArrayAdapter<CharSequence>(getContext(), android.R.layout.simple_list_item_1, items) {
            @Override public View getView(int position, View convertView, ViewGroup parent) {
                TextView row = (TextView)super.getView(position, convertView, parent);
                row.setTextColor(ui.theme.text); row.setTextSize(16); row.setSingleLine(false);
                row.setMinHeight(ui.dp(56)); row.setPadding(ui.dp(24), ui.dp(14), ui.dp(24), ui.dp(14));
                return row;
            }
        }, listener);
    }
    @Override public AlertDialog create() {
        AlertDialog dialog = super.create();
        dialog.setOnShowListener(ignored -> {
            Window window = dialog.getWindow();
            if (window != null) {
                GradientDrawable shape = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{ui.theme.mid, ui.theme.low});
                shape.setCornerRadius(ui.dp(24)); shape.setStroke(ui.dp(1), ui.theme.border);
                window.setBackgroundDrawable(shape); window.setDimAmount(.42f);
                window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
                int width = Math.min(activity.getResources().getDisplayMetrics().widthPixels - ui.dp(32), ui.dp(560));
                window.setLayout(width, ViewGroup.LayoutParams.WRAP_CONTENT);
            }
            for (int which : new int[]{DialogInterface.BUTTON_POSITIVE, DialogInterface.BUTTON_NEGATIVE, DialogInterface.BUTTON_NEUTRAL}) {
                Button button = dialog.getButton(which);
                if (button != null) { button.setAllCaps(false); button.setTextColor(ui.theme.accentText); button.setMinHeight(ui.dp(48)); }
            }
            if (dialog.getListView() != null) {
                dialog.getListView().setDivider(new ColorDrawable(ui.theme.border)); dialog.getListView().setDividerHeight(ui.dp(1));
            }
        });
        return dialog;
    }
}
