package android.os;
public class Handler {
    public Handler(Looper looper){}
    public boolean post(Runnable work){Looper.pending.add(work);return true;}
}
