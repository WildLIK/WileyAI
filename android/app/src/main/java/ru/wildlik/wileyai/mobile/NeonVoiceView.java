package ru.wildlik.wileyai.mobile;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.*;
import android.os.SystemClock;
import android.view.View;

/** Numeric-level visualizer. No audio buffers, microphone, or background work. */
final class NeonVoiceView extends View {
 enum Mode { IDLE, LISTENING, RECOGNIZING, PROCESSING, GENERATING, SPEAKING, SUCCESS, ERROR }
 private final WlPulse pulse=new WlPulse();private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);private final Path path=new Path();private final Matrix shaderMatrix=new Matrix();private final boolean logo;
 private final int[] colors={0xff00dfff,0xff287bff,0xff874bff,0xfff249e8};
 private final float[] spectrumTarget=new float[VoiceSpectrum.BANDS], spectrumLevel=new float[VoiceSpectrum.BANDS];
 private LinearGradient gradient,errorGradient,highlight;private final Matrix highlightMatrix=new Matrix();private Mode mode=Mode.IDLE;private float target,level;private long previous;private boolean reduced,logoAnimation=true,paused;private float intensity=1f;
 NeonVoiceView(Context c,boolean isLogo){super(c);logo=isLogo;setLayerType(View.LAYER_TYPE_SOFTWARE,null);setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);}
 void configure(int style,boolean animateLogo,boolean reduce){intensity=style==0?.65f:style==1?.85f:1f;logoAnimation=animateLogo;reduced=reduce;invalidate();}
 void state(Mode next){mode=next;if(next!=Mode.LISTENING)target=0;
  if(logo){WlPulse.Mode visual=switch(next){case LISTENING->WlPulse.Mode.LISTENING;case RECOGNIZING,PROCESSING,GENERATING,SPEAKING->WlPulse.Mode.PROCESSING;case SUCCESS->WlPulse.Mode.SUCCESS;case ERROR->WlPulse.Mode.ERROR;default->WlPulse.Mode.IDLE;};pulse.set(visual,SystemClock.uptimeMillis());}invalidate();}
 void level(float n){if(mode==Mode.LISTENING){float next=Math.max(0,Math.min(1,n));if(Math.abs(next-target)>.05f&&getWidth()>0){int blue=0xff424db2,pink=0xfff249e8;float a=next;int mix=Color.rgb((int)(Color.red(blue)*(1-a)+Color.red(pink)*a),(int)(Color.green(blue)*(1-a)+Color.green(pink)*a),(int)(Color.blue(blue)*(1-a)+Color.blue(pink)*a));gradient=new LinearGradient(0,0,getWidth(),0,new int[]{colors[0],colors[1],colors[2],mix},null,Shader.TileMode.CLAMP);}target=next;invalidate();}}
 void spectrum(float[] values){if(mode==Mode.LISTENING && values!=null){System.arraycopy(values,0,spectrumTarget,0,Math.min(values.length,spectrumTarget.length));invalidate();}}
 void paused(boolean value){paused=value;previous=0;if(!value)invalidate();}
 @Override protected void onSizeChanged(int w,int h,int oldw,int oldh){super.onSizeChanged(w,h,oldw,oldh);gradient=new LinearGradient(0,0,Math.max(1,w),0,colors,null,Shader.TileMode.CLAMP);errorGradient=new LinearGradient(0,0,Math.max(1,w),0,0xffff6b8c,0xffe34eb4,Shader.TileMode.CLAMP);highlight=new LinearGradient(0,0,Math.max(1,w)*.45f,0,new int[]{0x00ffffff,0xccffffff,0x00ffffff},null,Shader.TileMode.CLAMP);}
 @Override protected void onDraw(Canvas c){super.onDraw(c);if(getWidth()==0||getHeight()==0)return;long now=SystemClock.uptimeMillis();float dt=previous==0?.016f:Math.min(.1f,(now-previous)/1000f);previous=now;boolean anim=WlPulse.animates(!logo||logoAnimation,reduced,ValueAnimator.areAnimatorsEnabled(),!paused&&isShown()&&getWindowVisibility()==View.VISIBLE);float t=anim?now/1000f:0;
  WlPulse.Mode logoMode=logo?pulse.current(now):WlPulse.Mode.IDLE;double phase=WlPulse.phase(now,logoMode);
  float wanted=mode==Mode.LISTENING?target:mode==Mode.IDLE?.02f:mode==Mode.ERROR?.12f:.18f;level=NeonWaveMath.smooth(level,wanted,dt);
  shaderMatrix.reset();if(logo&&anim)shaderMatrix.setTranslate((float)Math.sin(phase)*getWidth()*.28f,0);if(gradient!=null)gradient.setLocalMatrix(shaderMatrix);paint.reset();paint.setAntiAlias(true);paint.setShader((logo?(anim && logoMode==WlPulse.Mode.ERROR):mode==Mode.ERROR)?errorGradient:gradient);paint.setStyle(Paint.Style.STROKE);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);
  if(logo){float side=Math.min(getWidth(),getHeight())*.80f;float x=(getWidth()-side)/2f,y=(getHeight()-side)/2f;float sw=Math.max(2,side*.115f);paint.setStrokeWidth(sw);float glow=anim?(float)(.8+.12*Math.sin(phase)): .8f; if(anim && logoMode==WlPulse.Mode.PROCESSING)glow+=.18f;paint.setShadowLayer(sw*glow,0,0,0x804b85ff);path.reset();path.moveTo(x+side*.04f,y+side*.22f);path.cubicTo(x+side*.13f,y+side*.02f,x+side*.22f,y+side*.24f,x+side*.31f,y+side*.72f);path.cubicTo(x+side*.38f,y+side*.88f,x+side*.47f,y+side*.26f,x+side*.57f,y+side*.25f);path.cubicTo(x+side*.66f,y+side*.24f,x+side*.65f,y+side*.78f,x+side*.73f,y+side*.76f);path.cubicTo(x+side*.81f,y+side*.73f,x+side*.87f,y+side*.16f,x+side*.96f,y+side*.16f);c.drawPath(path,paint);
   if(anim && highlight!=null && logoMode!=WlPulse.Mode.ERROR){highlightMatrix.reset();highlightMatrix.setTranslate((float)((.5+.5*Math.sin(phase))*getWidth()*.8-getWidth()*.2),0);highlight.setLocalMatrix(highlightMatrix);paint.clearShadowLayer();paint.setShader(highlight);paint.setStrokeWidth(sw*.52f);c.drawPath(path,paint);paint.setShader(gradient);paint.setStrokeWidth(sw);}
   path.reset();path.moveTo(x+side*.90f,y+side*.25f);path.lineTo(x+side*.74f,y+side*.76f);path.lineTo(x+side*.99f,y+side*.76f);c.drawPath(path,paint);
   // A narrower highlight follows the ribbon crest without adding separate ornaments.
   paint.setShader(null);paint.clearShadowLayer();paint.setColor(anim ? Color.argb((int)(100+35*(.5+.5*Math.sin(phase))),106,223,255) : 0x906adfff);paint.setStrokeWidth(sw*.19f);path.reset();path.moveTo(x+side*.05f,y+side*.21f);path.cubicTo(x+side*.14f,y+side*.04f,x+side*.24f,y+side*.28f,x+side*.31f,y+side*.57f);c.drawPath(path,paint);paint.setShader(gradient);
  }else{float w=getWidth(),h=getHeight(),mid=h*.5f;float motion=anim?t:0;float amp=NeonWaveMath.amplitude(h,level,intensity);
  paint.setStrokeWidth(Math.max(1f,w/(VoiceSpectrum.BANDS*2f)));paint.setAlpha(70);paint.clearShadowLayer();
  for(int i=0;i<VoiceSpectrum.BANDS;i++){float desired=mode==Mode.LISTENING?spectrumTarget[i]:0;spectrumLevel[i]=NeonWaveMath.smooth(spectrumLevel[i],desired,dt);float x=w*(i+.5f)/VoiceSpectrum.BANDS;float half=h*.46f*spectrumLevel[i];c.drawLine(x,mid-half,x,mid+half,paint);}
  int steps=Math.max(32,Math.min(100,(int)(w/5)));for(int layer=0;layer<2;layer++){path.reset();for(int i=0;i<=steps;i++){float u=i/(float)steps;float envelope=(float)Math.pow(Math.sin(Math.PI*u),.75);float wave=(float)(.68*Math.sin(u*14-motion*3+layer*.9)+.22*Math.sin(u*25+motion*1.7)+.10*Math.cos(u*37-motion));float yy=mid+amp*envelope*wave*(layer==0?1:.58f);if(i==0)path.moveTo(0,yy);else path.lineTo(w*u,yy);}paint.setStrokeWidth(getResources().getDisplayMetrics().density*(layer==0?2f:1f));paint.setAlpha(layer==0?(int)(150+105*level):110);paint.setShadowLayer(h*(.035f+.06f*level),0,0,0xaa168fff);c.drawPath(path,paint);}}
  paint.clearShadowLayer();paint.setShader(null);if(anim){if(logo)postInvalidateDelayed(logoMode==WlPulse.Mode.PROCESSING?33:100);else if(mode==Mode.IDLE)postInvalidateDelayed(66);else postInvalidateOnAnimation();}
 }
 @Override protected void onDetachedFromWindow(){previous=0;super.onDetachedFromWindow();}
}
