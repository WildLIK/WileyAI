package android.accessibilityservice;
import android.content.Context;
import android.view.accessibility.*;
import java.util.List;
public class AccessibilityService extends Context {
    public AccessibilityNodeInfo root, nextRoot;public int reads;
    public List<AccessibilityWindowInfo> windows;
    public AccessibilityNodeInfo getRootInActiveWindow(){reads++;return reads>1&&nextRoot!=null?nextRoot:root;}
    public List<AccessibilityWindowInfo> getWindows(){return windows;}
    public void onServiceConnected(){} public void onAccessibilityEvent(AccessibilityEvent event){} public void onInterrupt(){} public void onDestroy(){}
}
