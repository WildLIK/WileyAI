package ru.wildlik.wileyai.mobile;
/** Copies the microphone's reusable buffer before queuing it for recognition. */
final class PcmChunk {
    static short[] copy(short[] source,int length){return java.util.Arrays.copyOf(source,length);}
    private PcmChunk(){}
}
