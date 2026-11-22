package ru.wildlik.wileyai.mobile;

/** Side-effect-free decisions for restoring a source after explicit user choices. */
final class ChatHeaderPolicy {
    static boolean restorePc(boolean savedPc,boolean hasProfile){return savedPc && hasProfile;}
    static boolean matches(String target,String kind){
        if(target==null||kind==null)return false;
        return switch(target){case "cloud" -> kind.equals("DIRECT_CLOUD")||kind.equals("OFFICIAL_API");case "gateway" -> kind.equals("REMOTE_GATEWAY");case "account" -> kind.equals("ACCOUNT_OAUTH");default -> false;};
    }
    static boolean activateAfterSettings(String target,String before,String after){return before!=null&&after!=null&&!before.equals(after)&&matches(target,after);}
    private ChatHeaderPolicy(){}
}
