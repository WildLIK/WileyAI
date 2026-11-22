package android.view.accessibility;
import android.graphics.Rect;
import java.util.*;
public class AccessibilityNodeInfo {
    public String pkg="ru.wildlik.wileyai.mobile",name="android.view.View",text="",description="",hint="";public boolean password,sensitive,editable,visible=true,clickable,enabled=true;public int input,window=7;public List<AccessibilityNodeInfo> children=new ArrayList<>();
    public CharSequence getPackageName(){return pkg;} public CharSequence getClassName(){return name;} public int getWindowId(){return window;}
    public boolean isPassword(){return password;} public boolean isAccessibilityDataSensitive(){return sensitive;} public boolean isEditable(){return editable;}
    public int getInputType(){return input;} public boolean isVisibleToUser(){return visible;} public CharSequence getText(){return text;}public CharSequence getContentDescription(){return description;}
    public CharSequence getHintText(){return hint;} public boolean isSelected(){return false;}
    public boolean isClickable(){return clickable;} public boolean isEnabled(){return enabled;} public boolean isScrollable(){return false;}
    public void getBoundsInScreen(Rect r){r.left=1;r.top=2;r.right=3;r.bottom=4;} public int getChildCount(){return children.size();}
    public AccessibilityNodeInfo getChild(int i){return children.get(i);} public void recycle(){}
}
