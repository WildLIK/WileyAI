package ru.wildlik.wileyai.mobile;
final class NeonWaveMath {
 static float smooth(float current,float target,float dt){dt=Math.max(0,Math.min(.1f,dt));return current+(target-current)*(1-(float)Math.exp(-dt/(target>current?.045:.23)));}
 static float amplitude(float height,float level,float intensity){return Math.max(0,height)*(.035f+.43f*Math.max(0,Math.min(1,level))*Math.max(0,Math.min(1,intensity)));}
 static float normalize(double rms) { return (float)Math.max(0,Math.min(1,Math.sqrt(Math.log1p(Math.max(0,rms-100)/450.0)/Math.log(1+4000.0/450.0)))); }
 static final class LevelNormalizer {
  private double floor=100;
  float observe(double rms) {
   if(rms<floor*1.8) floor=Math.max(50,Math.min(500,floor*.98+rms*.02));
   return normalize(Math.max(0,rms-floor+100));
  }
 }
 private NeonWaveMath(){}
}
