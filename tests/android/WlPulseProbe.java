package ru.wildlik.wileyai.mobile;
public final class WlPulseProbe {
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  WlPulse p=new WlPulse();check(p.current(0)==WlPulse.Mode.IDLE);p.set(WlPulse.Mode.PROCESSING,100);check(p.current(300)==WlPulse.Mode.PROCESSING);
  p.set(WlPulse.Mode.SUCCESS,400);p.set(WlPulse.Mode.SUCCESS,800);check(p.current(1399)==WlPulse.Mode.SUCCESS);check(p.current(1400)==WlPulse.Mode.IDLE);check(p.current(2000)==WlPulse.Mode.IDLE);
  p.set(WlPulse.Mode.PROCESSING,2100);p.set(WlPulse.Mode.ERROR,2200);check(p.current(3200)==WlPulse.Mode.IDLE);
  p.set(WlPulse.Mode.LISTENING,3300);p.set(WlPulse.Mode.PROCESSING,3400);check(p.current(4000)==WlPulse.Mode.PROCESSING);p.set(WlPulse.Mode.IDLE,4100);check(p.current(4100)==WlPulse.Mode.IDLE);
  check(!WlPulse.animates(false,false,true,true));check(!WlPulse.animates(true,true,true,true));check(!WlPulse.animates(true,false,false,true));check(!WlPulse.animates(true,false,true,false));check(WlPulse.animates(true,false,true,true));
  check(Math.abs(WlPulse.phase(0,WlPulse.Mode.IDLE)-WlPulse.phase(5500,WlPulse.Mode.IDLE))<1e-6);check(Math.abs(WlPulse.phase(17,WlPulse.Mode.PROCESSING)-WlPulse.phase(2817,WlPulse.Mode.PROCESSING))<1e-6);
 }
}
