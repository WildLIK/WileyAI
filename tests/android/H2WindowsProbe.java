package ru.wildlik.wileyai.mobile;
import java.util.Arrays;

public class H2WindowsProbe {
    public static void main(String[] args) {
        H2Windows q=new H2Windows();
        short[] audio=new short[4096];
        Arrays.fill(audio,(short)17);
        q.feed(1,0,audio,2048);
        H2Windows.Slot s=q.next();
        check(s.end==1280 && s.pcm[14720]==17 && s.pcm[14719]==0);
        q.release(s);
        q.feed(1,2048,audio,4096);
        q.feed(1,6144,audio,4096);
        check(q.dropped==4);
        q.end(1);
        while((s=q.next())!=null) q.release(s);
        Arrays.fill(audio,(short)3);
        q.feed(2,0,audio,1280);
        s=q.next();check(s.capture==2 && s.pcm[0]==0 && s.pcm[15999]==3);
        q.release(s);
        q.feed(2,54000,audio,2048);
        check(q.next()==null && q.warmup>0);
        q.close();
        q.feed(3,0,audio,1280);
        check(q.next()==null);
        H2Windows.Decision d=new H2Windows.Decision();
        check(!d.update(1,1280,.2f) && d.update(1,2560,.2f));
        check(!d.update(1,3840,.2f) && !d.update(1,5120,0f) && !d.update(1,6400,.2f) && !d.update(1,7680,.2f));
        check(!d.update(1,17920,.2f) && d.update(1,19200,.2f));
        check(!d.update(2,1280,.2f) && d.update(2,2560,.2f));
    }
    static void check(boolean good) {if(!good) throw new AssertionError();}
}
