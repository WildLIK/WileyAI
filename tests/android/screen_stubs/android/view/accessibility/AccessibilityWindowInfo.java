package android.view.accessibility;
public class AccessibilityWindowInfo {
    public static final int TYPE_APPLICATION=1,TYPE_INPUT_METHOD=2,TYPE_ACCESSIBILITY_OVERLAY=4;
    public int id=8,type=TYPE_APPLICATION;public AccessibilityNodeInfo root;
    public int getId(){return id;} public int getType(){return type;}
    public AccessibilityNodeInfo getRoot(){return root;} public void recycle(){}
}
