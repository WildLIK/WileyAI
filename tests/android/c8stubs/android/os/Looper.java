package android.os;
import java.util.concurrent.ConcurrentLinkedQueue;
public class Looper {
    public static final ConcurrentLinkedQueue<Runnable> pending=new ConcurrentLinkedQueue<>();
    public static Looper getMainLooper(){return new Looper();}
    public static void drain(){Runnable r;while((r=pending.poll())!=null)r.run();}
}
