package ru.wildlik.wileyai.mobile;

/** Fixed-vocabulary description of an accepted final hypothesis. No speech is retained. */
record WakeActivation(long id,long detectedAt,int variant,boolean conversation,int confidenceMilli,long lagMillis) {
    /** Main-loop claim: block the decoder until the matching Android window arrives or expires. */
    static final class Gate {
        private WakeActivation pending;
        boolean reserve(WakeActivation event){
            if(pending!=null)return false;
            pending=event;
            return true;
        }
        boolean waiting(){return pending!=null;}
        boolean matches(long id){return pending!=null&&pending.id()==id;}
        WakeActivation take(){WakeActivation result=pending;pending=null;return result;}
    }
}
