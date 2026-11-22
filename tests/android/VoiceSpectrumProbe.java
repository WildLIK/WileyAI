package ru.wildlik.wileyai.mobile;
public final class VoiceSpectrumProbe {
 public static void main(String[] args){
  VoiceSpectrum fft=new VoiceSpectrum(); short[] audio=new short[2048];
  if(VoiceSpectrum.displayLevel(.05)!=0 || VoiceSpectrum.displayLevel(1)<=.3 || VoiceSpectrum.displayLevel(1)>=1) throw new AssertionError("visible spectrum gain");
  float[] quiet=fft.analyze(audio,audio.length);for(float x:quiet)if(x!=0)throw new AssertionError("silence");
  for(int bin:new int[]{4,16,64,128}) {for(int i=0;i<audio.length;i++)audio[i]=(short)(12000*Math.sin(2*Math.PI*bin*i/512));float[] bars=fft.analyze(audio,audio.length);int best=0;for(int j=1;j<bars.length;j++)if(bars[j]>bars[best])best=j;int lo=1+best*best*250/(16*16),hi=1+(best+1)*(best+1)*250/(16*16);if(bin<lo||bin>=Math.max(lo+1,hi))throw new AssertionError("bin "+bin+" band "+best);}
  if(!(NeonWaveMath.normalize(314)<NeonWaveMath.normalize(567)&&NeonWaveMath.normalize(567)<NeonWaveMath.normalize(1978)&&NeonWaveMath.normalize(1978)<1))throw new AssertionError("dynamic range");
 }
}
