package ru.wildlik.wileyai.mobile;

import android.animation.ValueAnimator;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Rect;
import android.graphics.Shader;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.view.View;
import android.view.WindowInsets;
import java.io.InputStream;
import java.lang.ref.WeakReference;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.BooleanSupplier;

/** One passive View for the supplied artwork and low-frequency decorations. */
final class ArtThemeView extends View {
    private static final ExecutorService LOADER=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"art-theme-loader");t.setDaemon(true);return t;});
    private static String cacheKey="";private static WeakReference<Bitmap> cache=new WeakReference<>(null);
    private final String theme;private final boolean live;private final BooleanSupplier busy;private final int fill;
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG|Paint.FILTER_BITMAP_FLAG);private final RectF imageRect=new RectF();
    private final Path petal=new Path();private final Handler main=new Handler(Looper.getMainLooper());
    private Bitmap bitmap;private Shader upperGlow,lowerGlow;private boolean attached,resumed=true,visible=true,powerSaving;private boolean registered;
    private int unobscuredHeight,layoutWidth;
    private final Runnable tick=()->{if(canAnimate())invalidate();};
    private final BroadcastReceiver powerReceiver=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){refreshPower();}};
    ArtThemeView(Context context,String theme,boolean live,int fill,BooleanSupplier busy){
        super(context);this.theme=theme;this.live=live;this.fill=fill;this.busy=busy;setWillNotDraw(false);setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        petal.moveTo(0,-1);petal.cubicTo(.9f,-.65f,1,.45f,0,1);petal.cubicTo(-.9f,.45f,-.9f,-.65f,0,-1);petal.close();refreshPower();
    }
    private void refreshPower(){PowerManager p=(PowerManager)getContext().getSystemService(Context.POWER_SERVICE);powerSaving=p!=null&&p.isPowerSaveMode();removeCallbacks(tick);invalidate();}
    void paused(boolean value){resumed=!value;removeCallbacks(tick);if(resumed)invalidate();}
    private boolean canAnimate(){return ArtThemeMath.animate(live,attached,visible,resumed,powerSaving,ValueAnimator.areAnimatorsEnabled());}
    @Override protected void onAttachedToWindow(){super.onAttachedToWindow();attached=true;visible=isShown()&&getWindowVisibility()==VISIBLE;
        try{IntentFilter f=new IntentFilter(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED);if(Build.VERSION.SDK_INT>=33)getContext().registerReceiver(powerReceiver,f,Context.RECEIVER_NOT_EXPORTED);else getContext().registerReceiver(powerReceiver,f);registered=true;}catch(RuntimeException ignored){}
        final Context app=getContext().getApplicationContext();final String key=theme;WeakReference<ArtThemeView> ref=new WeakReference<>(this);
        LOADER.execute(()->{Bitmap result; synchronized(ArtThemeView.class){result=cacheKey.equals(key)?cache.get():null;}
            if(result==null){try(InputStream in=app.getAssets().open("art_themes/"+key+".webp")){result=BitmapFactory.decodeStream(in);}catch(Exception ignored){return;}
                if(result!=null)synchronized(ArtThemeView.class){cacheKey=key;cache=new WeakReference<>(result);}}
            final Bitmap decoded=result;ArtThemeView view=ref.get();if(view!=null&&decoded!=null)view.main.post(()->{ArtThemeView target=ref.get();if(target!=null&&target.attached&&target.theme.equals(key)){target.bitmap=decoded;target.updateRect();target.invalidate();}});
        });
    }
    @Override protected void onDetachedFromWindow(){attached=false;removeCallbacks(tick);bitmap=null;if(registered){try{getContext().unregisterReceiver(powerReceiver);}catch(IllegalArgumentException ignored){}registered=false;}super.onDetachedFromWindow();}
    @Override protected void onWindowVisibilityChanged(int visibility){super.onWindowVisibilityChanged(visibility);visible=visibility==VISIBLE&&isShown();removeCallbacks(tick);if(visible)invalidate();}
    @Override public void onVisibilityAggregated(boolean shown){super.onVisibilityAggregated(shown);visible=shown&&getWindowVisibility()==VISIBLE;removeCallbacks(tick);if(visible)invalidate();}
    @Override protected void onSizeChanged(int w,int h,int oldw,int oldh){super.onSizeChanged(w,h,oldw,oldh);if(w!=layoutWidth){layoutWidth=w;unobscuredHeight=0;}updateRect();
        upperGlow=new RadialGradient(w*.42f,h*.17f,Math.max(1,w*.58f),0x8860eaff,0x0060eaff,Shader.TileMode.CLAMP);
        lowerGlow=new RadialGradient(w*.52f,h*.60f,Math.max(1,w*.50f),0x664fbfff,0x004fbfff,Shader.TileMode.CLAMP);
    }
    private boolean keyboardVisible(){WindowInsets insets=getRootWindowInsets();if(Build.VERSION.SDK_INT>=30&&insets!=null)return insets.isVisible(WindowInsets.Type.ime());
        Rect frame=new Rect();getWindowVisibleDisplayFrame(frame);int rootHeight=getRootView().getHeight();return rootHeight>0&&rootHeight-frame.bottom>rootHeight/4;}
    @Override public WindowInsets onApplyWindowInsets(WindowInsets insets){WindowInsets result=super.onApplyWindowInsets(insets);invalidate();return result;}
    private void updateRect(){if(bitmap==null)return;boolean keyboard=keyboardVisible();int height=getHeight();if(!keyboard)unobscuredHeight=Math.max(unobscuredHeight,height);
        if(keyboard&&unobscuredHeight==0&&Build.VERSION.SDK_INT>=30){WindowInsets insets=getRootWindowInsets();if(insets!=null)unobscuredHeight=height+Math.max(0,insets.getInsets(WindowInsets.Type.ime()).bottom-insets.getInsets(WindowInsets.Type.systemBars()).bottom);}
        int canvasHeight=ArtThemeMath.backgroundHeight(height,unobscuredHeight,keyboard);float f=theme.equals("ice")?.38f:theme.equals("ember")?.34f:theme.equals("nebula")?.36f:.43f;float[] r=ArtThemeMath.imageRect(getWidth(),canvasHeight,bitmap.getWidth(),bitmap.getHeight(),f);imageRect.set(r[0],r[1],r[2],r[3]);}
    @Override protected void onDraw(Canvas c){super.onDraw(c);if(bitmap==null)return;updateRect();c.drawColor(fill);paint.setAlpha(255);paint.setShader(null);c.drawBitmap(bitmap,null,imageRect,paint);
        boolean moving=canAnimate();if(moving){long ms=SystemClock.uptimeMillis();double t=ms/1000.0;
            if(theme.equals("aurora")){glow(c,upperGlow,(int)(18+8*Math.sin(t*.22)));glow(c,lowerGlow,(int)(8+4*Math.sin(t*.17)));}
            else if(theme.equals("ice")){glow(c,upperGlow,(int)(8+3*Math.sin(t*.15)));snow(c,t);}
            else if(theme.equals("ember")){glow(c,upperGlow,(int)(6+3*Math.sin(t*.19)));petals(c,t);}
            else {glow(c,upperGlow,(int)(7+3*Math.sin(t*.11)));stars(c,t);}
        }
        c.drawColor(theme.equals("ice")?0xc4e8f3fb:theme.equals("ember")?0x9906000a:0x99030715);
        removeCallbacks(tick);if(moving)postDelayed(tick,busy!=null&&busy.getAsBoolean()?200:83);
    }
    private void glow(Canvas c,Shader shader,int alpha){if(shader==null)return;paint.setShader(shader);paint.setAlpha(Math.max(0,Math.min(255,alpha)));c.drawRect(0,0,getWidth(),getHeight(),paint);paint.setShader(null);}
    private void snow(Canvas c,double t){paint.setColor(Color.WHITE);for(int i=0;i<18;i++){float size=(.6f+ArtThemeMath.phase(i,.618f)*1.8f)*getResources().getDisplayMetrics().density;float x=(float)((ArtThemeMath.phase(i,.754f)*getWidth()+t*(6+i%4*3))%Math.max(1,getWidth()));float y=(float)((ArtThemeMath.phase(i,.381f)*getHeight()+t*(10+i%5*3))%Math.max(1,getHeight()));paint.setAlpha(35+(i%4)*12);c.drawCircle(x,y,size,paint);}}
    private void petals(Canvas c,double t){paint.setColor(0xffff607b);for(int i=0;i<7;i++){float size=(1.8f+ArtThemeMath.phase(i,.618f)*2.3f)*getResources().getDisplayMetrics().density;float y=(float)((ArtThemeMath.phase(i,.451f)*getHeight()+t*(8+i%3*2))%Math.max(1,getHeight()));float x=(float)((ArtThemeMath.phase(i,.736f)*getWidth()+Math.sin(t*.35+i)*getWidth()*.025+getWidth())%Math.max(1,getWidth()));paint.setAlpha(70+i%3*14);c.save();c.translate(x,y);c.rotate((float)(t*12+i*47));c.scale(size,size*.55f);c.drawPath(petal,paint);c.restore();}}
    private void stars(Canvas c,double t){paint.setColor(0xffd1c9ff);for(int i=0;i<14;i++){float x=ArtThemeMath.phase(i,.719f)*getWidth();float y=ArtThemeMath.phase(i,.437f)*getHeight()*.7f;float radius=(.4f+ArtThemeMath.phase(i,.619f)*.8f)*getResources().getDisplayMetrics().density;paint.setAlpha((int)(35+25*(1+Math.sin(t*.55+i))));c.drawCircle(x,y,radius,paint);}}
}
