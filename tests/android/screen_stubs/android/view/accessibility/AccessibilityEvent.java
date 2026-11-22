package android.view.accessibility;
public class AccessibilityEvent {
    public static final int TYPE_WINDOW_STATE_CHANGED=32;
    public int type,windowId=-1;public CharSequence pkg,name;
    public int getEventType(){return type;} public CharSequence getPackageName(){return pkg;}
    public CharSequence getClassName(){return name;} public int getWindowId(){return windowId;}
}
