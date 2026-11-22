package ru.wildlik.wileyai.mobile;

/** Short-lived PCM analysis on the capture worker; only numeric bands leave this object. */
final class VoiceSpectrum {
    static final int SIZE = 512, BANDS = 16;
    private final double[] re = new double[SIZE], im = new double[SIZE];
    static float displayLevel(double peak) {
        // Suppress a low-level noise floor, then expose speech dynamics without hard saturation.
        double audible=Math.max(0, peak-0.08);
        return (float)Math.sqrt(audible/(audible+2.5));
    }
    float[] analyze(short[] pcm, int count) {
        for (int i=0; i<SIZE; i++) {
            int index = Math.max(0, count-SIZE)+i;
            double sample = index < count ? pcm[index] / 32768.0 : 0;
            re[i]=sample*(0.5-0.5*Math.cos(2*Math.PI*i/(SIZE-1))); im[i]=0;
        }
        for(int i=1,j=0;i<SIZE;i++) { int bit=SIZE>>1; for(; (j&bit)!=0; bit>>=1) j^=bit; j^=bit; if(i<j){double t=re[i];re[i]=re[j];re[j]=t;} }
        for(int len=2;len<=SIZE;len<<=1) { double angle=-2*Math.PI/len, wr0=Math.cos(angle), wi0=Math.sin(angle);
            for(int base=0;base<SIZE;base+=len){double wr=1,wi=0;for(int j=0;j<len/2;j++){
                int a=base+j,b=a+len/2;double tr=wr*re[b]-wi*im[b],ti=wr*im[b]+wi*re[b];
                re[b]=re[a]-tr;im[b]=im[a]-ti;re[a]+=tr;im[a]+=ti;double next=wr*wr0-wi*wi0;wi=wr*wi0+wi*wr0;wr=next;
            }}
        }
        float[] bands=new float[BANDS];
        for(int band=0;band<BANDS;band++) { int lo=1+(band*band*250)/(BANDS*BANDS), hi=1+((band+1)*(band+1)*250)/(BANDS*BANDS); hi=Math.max(lo+1,hi); double peak=0;
            for(int bin=lo;bin<hi && bin<SIZE/2;bin++)peak=Math.max(peak,Math.hypot(re[bin],im[bin]));
            bands[band]=displayLevel(peak);
        }
        return bands;
    }
}
