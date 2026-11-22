package ru.wildlik.wileyai.mobile;

import java.util.Arrays;

public final class PcmRingBufferProbe {
    private static void same(short[] expected,short[] actual){if(!Arrays.equals(expected,actual))throw new AssertionError(Arrays.toString(actual));}
    public static void main(String[] args){
        PcmRingBuffer ring=new PcmRingBuffer(4);
        ring.append(new short[]{1,2,3},0,3);same(new short[]{1,2,3},ring.snapshot());
        ring.append(new short[]{4,5},0,2);same(new short[]{2,3,4,5},ring.snapshot());
        short[] copy=ring.snapshot();copy[0]=99;same(new short[]{2,3,4,5},ring.snapshot());
        ring.append(new short[]{6,7,8,9,10,11},0,6);same(new short[]{8,9,10,11},ring.drain());same(new short[]{},ring.snapshot());
        ring.append(new short[]{1,2,3},1,2);same(new short[]{2,3},ring.snapshot());ring.clear();same(new short[]{},ring.snapshot());
        try{ring.append(new short[]{1},0,2);throw new AssertionError("range accepted");}catch(IllegalArgumentException expected){}
        try{new PcmRingBuffer(0);throw new AssertionError("capacity accepted");}catch(IllegalArgumentException expected){}
    }
}
