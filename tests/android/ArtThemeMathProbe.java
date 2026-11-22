package ru.wildlik.wileyai.mobile;
public final class ArtThemeMathProbe {
 static void check(boolean v){if(!v)throw new AssertionError();}
 static void close(float a,float b){check(Math.abs(a-b)<.02f);}
 public static void main(String[] args){
  float[] p=ArtThemeMath.imageRect(1080,2340,465,836,.4f);float pw=p[2]-p[0],ph=p[3]-p[1];close(pw/ph,465f/836);check(p[0]<=0&&p[2]>=1080&&p[1]<=0&&p[3]>=2340);
  float[] narrow=ArtThemeMath.imageRect(840,2340,465,836,.4f);close((narrow[2]-narrow[0])/(narrow[3]-narrow[1]),465f/836);check(narrow[0]<=0&&narrow[2]>=840);
  float[] wide=ArtThemeMath.imageRect(2100,1200,465,836,.4f);close(wide[3]-wide[1],1200);check(wide[0]>0&&wide[2]<2100);
  check(ArtThemeMath.backgroundHeight(1345,2207,true)==2207);check(ArtThemeMath.backgroundHeight(1345,2207,false)==1345);
  float[] keyboard=ArtThemeMath.imageRect(1080,ArtThemeMath.backgroundHeight(1345,2207,true),465,836,.4f);check(keyboard[0]<=0&&keyboard[2]>=1080);
  check(ArtThemeMath.animate(true,true,true,true,false,true));check(!ArtThemeMath.animate(false,true,true,true,false,true));check(!ArtThemeMath.animate(true,false,true,true,false,true));check(!ArtThemeMath.animate(true,true,false,true,false,true));check(!ArtThemeMath.animate(true,true,true,false,false,true));check(!ArtThemeMath.animate(true,true,true,true,true,true));check(!ArtThemeMath.animate(true,true,true,true,false,false));
  for(int i=0;i<50;i++){float p1=ArtThemeMath.phase(i,.618f);check(p1>=0&&p1<1);check(p1==ArtThemeMath.phase(i,.618f));}
 }
}
