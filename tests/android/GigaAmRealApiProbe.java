package ru.wildlik.wileyai.mobile;
import java.lang.reflect.*;
public final class GigaAmRealApiProbe {
 public static void main(String[] args)throws Exception {
  Method config=GigaAmSherpa.class.getDeclaredMethod("config",String.class);config.setAccessible(true);
  Method set=GigaAmSherpa.class.getDeclaredMethod("set",Object.class,String.class,Object.class);set.setAccessible(true);
  Object feat=config.invoke(null,"FeatureConfig");set.invoke(null,feat,"sampleRate",16000);set.invoke(null,feat,"featureDim",64);set.invoke(null,feat,"dither",0f);
  Object trans=config.invoke(null,"OfflineTransducerModelConfig");set.invoke(null,trans,"encoder","e");set.invoke(null,trans,"decoder","d");set.invoke(null,trans,"joiner","j");
  Object model=config.invoke(null,"OfflineModelConfig");set.invoke(null,model,"transducer",trans);set.invoke(null,model,"modelType","nemo_transducer");set.invoke(null,model,"tokens","t");set.invoke(null,model,"numThreads",2);set.invoke(null,model,"debug",false);
  Object recognition=config.invoke(null,"OfflineRecognizerConfig");set.invoke(null,recognition,"featConfig",feat);set.invoke(null,recognition,"modelConfig",model);set.invoke(null,recognition,"decodingMethod","greedy_search");
  if(!feat.getClass().getMethod("getFeatureDim").invoke(feat).equals(64))throw new AssertionError();
  System.out.println("Real sherpa configuration API works");
 }
}
