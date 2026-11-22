package ru.wildlik.wileyai.mobile;
/** Monotonic-time visual state only. Never starts or stops work. */
final class WlPulse {
 enum Mode { IDLE, LISTENING, PROCESSING, SUCCESS, ERROR }
 private Mode mode=Mode.IDLE; private long entered;
 void set(Mode next,long now){if(next!=mode){mode=next;entered=now;}}
 Mode current(long now){if((mode==Mode.SUCCESS||mode==Mode.ERROR)&&now-entered>=1000)mode=Mode.IDLE;return mode;}
 static double phase(long now,Mode mode){long duration=mode==Mode.PROCESSING?2800:mode==Mode.LISTENING?4200:5500;return 2*Math.PI*(now%duration)/(double)duration;}
 static boolean animates(boolean enabled,boolean reduced,boolean systemEnabled,boolean visible){return enabled&&!reduced&&systemEnabled&&visible;}
}
