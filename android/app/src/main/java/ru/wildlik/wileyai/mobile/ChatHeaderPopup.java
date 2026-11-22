package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.ScrollView;
import android.widget.TextView;

/** A small, bounded, anchored menu. The caller owns all selection and cancellation logic. */
final class ChatHeaderPopup {
    private final Activity activity;
    private final MobileUi ui;
    private final View anchor;
    private final ScrollView scroll;
    private final LinearLayout rows;
    private final PopupWindow popup;
    private final int width;

    ChatHeaderPopup(Activity activity, MobileUi ui, View anchor) {
        this.activity=activity;this.ui=ui;this.anchor=anchor;
        Rect frame=new Rect();anchor.getWindowVisibleDisplayFrame(frame);
        width=Math.max(ui.dp(180),Math.min(ui.dp(340),frame.width()-ui.dp(16)));
        scroll=new ScrollView(activity);scroll.setFillViewport(false);
        rows=ui.vertical();rows.setPadding(ui.dp(7),ui.dp(6),ui.dp(7),ui.dp(6));scroll.addView(rows);
        popup=new PopupWindow(scroll,width,ViewGroup.LayoutParams.WRAP_CONTENT,true);
        GradientDrawable surface=ui.panel(ui.theme.low,18);surface.setStroke(ui.dp(1),ui.theme.accent);
        popup.setBackgroundDrawable(surface);popup.setOutsideTouchable(true);popup.setElevation(ui.dp(10));
        popup.setInputMethodMode(PopupWindow.INPUT_METHOD_NEEDED);
        popup.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        popup.setOnDismissListener(()->anchor.setSelected(false));
    }
    void clear(){rows.removeAllViews();}
    void label(String title){TextView view=ui.text(title,12,ui.theme.secondary);view.setPadding(ui.dp(10),ui.dp(7),ui.dp(10),ui.dp(5));rows.addView(view);}
    void row(String title,String detail,int icon,boolean selected,Runnable action){
        LinearLayout row=ui.row();row.setPadding(ui.dp(9),ui.dp(6),ui.dp(9),ui.dp(6));row.setMinimumHeight(ui.dp(48));
        row.setBackground(ui.interactive(android.graphics.Color.TRANSPARENT,ui.theme.high,12));row.setSelected(selected);row.setFocusable(true);
        if(icon!=0){android.widget.ImageView image=new android.widget.ImageView(activity);image.setImageResource(icon);image.setColorFilter(selected?ui.theme.accentText:ui.theme.secondary);LinearLayout.LayoutParams ip=new LinearLayout.LayoutParams(ui.dp(20),ui.dp(20));ip.setMargins(0,0,ui.dp(10),0);row.addView(image,ip);}
        LinearLayout labels=ui.vertical();TextView heading=ui.text(title,15,selected?ui.theme.accentText:ui.theme.text);ui.typography(heading,selected?600:500);heading.setMaxLines(2);heading.setEllipsize(android.text.TextUtils.TruncateAt.END);labels.addView(heading);
        if(detail!=null&&!detail.isEmpty()){TextView description=ui.text(detail,12,ui.theme.secondary);description.setMaxLines(2);description.setEllipsize(android.text.TextUtils.TruncateAt.END);labels.addView(description);}
        row.addView(labels,new LinearLayout.LayoutParams(0,-2,1));row.setContentDescription(title+(detail==null||detail.isEmpty()?"":". "+detail));
        row.setOnClickListener(v->{dismiss();action.run();});rows.addView(row,new LinearLayout.LayoutParams(-1,-2));
        View divider=new View(activity);divider.setBackgroundColor(ui.theme.border);LinearLayout.LayoutParams d=new LinearLayout.LayoutParams(-1,ui.dp(1));d.setMargins(ui.dp(9),0,ui.dp(9),0);rows.addView(divider,d);
    }
    void show(){
        Rect frame=new Rect();anchor.getWindowVisibleDisplayFrame(frame);
        scroll.measure(View.MeasureSpec.makeMeasureSpec(width,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));
        popup.setHeight(Math.min(scroll.getMeasuredHeight(),Math.max(ui.dp(150),Math.min(ui.dp(420),frame.height()-ui.dp(24)))));
        int[] at=new int[2];anchor.getLocationOnScreen(at);int offset=Math.min(0,frame.right-ui.dp(8)-(at[0]+width));
        anchor.setSelected(true);popup.showAsDropDown(anchor,offset,ui.dp(4),Gravity.START);
    }
    void resize(){if(popup.isShowing()){Rect frame=new Rect();anchor.getWindowVisibleDisplayFrame(frame);scroll.measure(View.MeasureSpec.makeMeasureSpec(width,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));popup.update(width,Math.min(scroll.getMeasuredHeight(),Math.max(ui.dp(150),Math.min(ui.dp(420),frame.height()-ui.dp(24)))));}}
    boolean showing(){return popup.isShowing();}
    void dismiss(){popup.dismiss();}
}
