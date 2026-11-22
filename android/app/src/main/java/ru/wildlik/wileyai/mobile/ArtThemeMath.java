package ru.wildlik.wileyai.mobile;

/** Pure layout and policy calculations for the artistic background. */
final class ArtThemeMath {
    static int backgroundHeight(int visibleHeight,int unobscuredHeight,boolean keyboardVisible){
        return keyboardVisible?Math.max(visibleHeight,unobscuredHeight):visibleHeight;
    }
    static float[] imageRect(int width,int height,int imageWidth,int imageHeight,float focusY){
        if(width<=0||height<=0||imageWidth<=0||imageHeight<=0)return new float[]{0,0,0,0};
        float ratio=(float)width/height, imageRatio=(float)imageWidth/imageHeight;
        float scale=ratio>imageRatio*1.35f?(float)height/imageHeight:Math.max((float)width/imageWidth,(float)height/imageHeight);
        float w=imageWidth*scale,h=imageHeight*scale,x=(width-w)/2f;
        float focus=Math.max(0,Math.min(1,focusY));float y=h>height?(height-h)*focus:(height-h)/2f;
        return new float[]{x,y,x+w,y+h};
    }
    static boolean animate(boolean live,boolean attached,boolean visible,boolean resumed,boolean powerSaving,boolean systemAnimations){
        return live&&attached&&visible&&resumed&&!powerSaving&&systemAnimations;
    }
    static float phase(int index,float seed){float x=(index+1)*seed;return x-(float)Math.floor(x);}
    private ArtThemeMath(){}
}
