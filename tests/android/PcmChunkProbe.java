package ru.wildlik.wileyai.mobile;
public final class PcmChunkProbe {
 public static void main(String[] args){short[] audio={1,2,3};short[] first=PcmChunk.copy(audio,3);audio[0]=9;short[] second=PcmChunk.copy(audio,2);audio[1]=8;if(first[0]!=1||first[1]!=2||second[0]!=9||second[1]!=2)throw new AssertionError("PCM frames were overwritten");}
}
