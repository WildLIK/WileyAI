package ru.wildlik.wileyai.mobile;
public final class ChatHeaderPolicyProbe {
 static void check(boolean value){if(!value)throw new AssertionError();}
 public static void main(String[] args){
  check(!ChatHeaderPolicy.restorePc(true,false));check(ChatHeaderPolicy.restorePc(true,true));check(!ChatHeaderPolicy.restorePc(false,true));
  check(!ChatHeaderPolicy.activateAfterSettings("cloud","LOCAL","LOCAL"));
  check(ChatHeaderPolicy.activateAfterSettings("cloud","LOCAL","DIRECT_CLOUD"));
  check(ChatHeaderPolicy.activateAfterSettings("cloud","REMOTE_GATEWAY","OFFICIAL_API"));
  check(!ChatHeaderPolicy.activateAfterSettings("gateway","LOCAL","OFFICIAL_API"));
  check(ChatHeaderPolicy.activateAfterSettings("gateway","LOCAL","REMOTE_GATEWAY"));
  check(ChatHeaderPolicy.activateAfterSettings("account","LOCAL","ACCOUNT_OAUTH"));
  check(!ChatHeaderPolicy.activateAfterSettings("account","ACCOUNT_OAUTH","ACCOUNT_OAUTH"));
  check(!ChatHeaderPolicy.activateAfterSettings("cloud",null,"DIRECT_CLOUD"));
 }
}
