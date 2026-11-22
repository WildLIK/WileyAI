package ru.wildlik.wileyai.mobile;

import java.util.Arrays;
import java.nio.file.Files;
import java.nio.file.Paths;

public final class PcmHandoffProbe {
    static void check(boolean ok) { if (!ok) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        if (args.length >= 1) {
            byte[] raw=Files.readAllBytes(Paths.get(args[0]));
            check(raw.length%2==0);short[] samples=new short[raw.length/2];
            for(int i=0;i<samples.length;i++) samples[i]=(short)((raw[i*2]&255)|(raw[i*2+1]<<8));
            int boundary=args.length>1?Integer.parseInt(args[1]):samples.length/3, detection=Math.min(samples.length,boundary+100);
            PcmHandoff wav=new PcmHandoff(samples.length,samples.length);
            wav.append(Arrays.copyOfRange(samples,0,detection),detection);wav.activate(boundary);
            wav.append(Arrays.copyOfRange(samples,detection,samples.length),samples.length-detection);
            short[] out=new short[samples.length-boundary],chunk=new short[137];int pos=0;
            while(pos<out.length){int n=wav.read(chunk,10);check(n>0);System.arraycopy(chunk,0,out,pos,n);pos+=n;}
            check(Arrays.equals(out,Arrays.copyOfRange(samples,boundary,samples.length)));wav.close();
        }
        for (int split : new int[] {3, 6, 9}) {
            PcmHandoff pipe = new PcmHandoff(20, 40);
            short[] all = new short[20];
            for (int i=0; i<all.length; i++) all[i]=(short)(i+1);
            pipe.append(Arrays.copyOfRange(all,0,split),split);
            // Wake ends inside retained audio: deliver only command, then all new samples.
            int boundary = Math.max(0,split-2);
            pipe.activate(boundary);
            short[] next=Arrays.copyOfRange(all,split,all.length);
            pipe.append(next,next.length);
            short[] got=new short[20-boundary];int pos=0;short[] chunk=new short[3];
            while(pos<got.length){int n=pipe.read(chunk,10);check(n>0);System.arraycopy(chunk,0,got,pos,n);pos+=n;}
            check(Arrays.equals(got,Arrays.copyOfRange(all,boundary,all.length)));
            check(pipe.read(chunk,1)==0);pipe.close();check(pipe.read(chunk,1)==-1);pipe.close();
        }
        PcmHandoff old = new PcmHandoff(2,4);
        old.append(new short[]{1,2,3},3);
        try {old.activate(0);throw new AssertionError();} catch(IllegalArgumentException expected) {}
        old.activate(2);short[] b=new short[2];check(old.read(b,1)==1 && b[0]==3);old.close();
        PcmHandoff overflow=new PcmHandoff(3,2);overflow.activate(0);
        try {overflow.append(new short[]{1,2,3},3);throw new AssertionError();} catch(IllegalStateException expected) {}
        try {overflow.read(b,1);throw new AssertionError();} catch(IllegalStateException expected) {}
        overflow.close();
        // Stop producer without losing samples captured before the cutoff.
        PcmHandoff sealed = new PcmHandoff(8,16);sealed.activate(0);sealed.append(new short[]{11,12,13},3);sealed.seal();
        check(!sealed.isActive());check(sealed.read(b,1)==2 && b[0]==11 && b[1]==12);check(sealed.read(b,1)==1 && b[0]==13);check(sealed.read(b,1)==-1);
        check(sealed.stats().discardedSamples()==0);sealed.close();sealed.close();
        PcmHandoff abort=new PcmHandoff(8,16);abort.activate(0);abort.append(new short[]{1,2},2);abort.close();check(abort.stats().discardedSamples()==2);check(abort.read(b,1)==-1);
        PcmHandoff concurrent=new PcmHandoff(32,256);concurrent.activate(0);
        Thread producer=new Thread(()->{for(short i=0;i<100;i++)concurrent.append(new short[]{i},1);});
        producer.start();for(short i=0;i<100;i++){check(concurrent.read(b,1000)==1);check(b[0]==i);}producer.join();concurrent.close();
    }
}
