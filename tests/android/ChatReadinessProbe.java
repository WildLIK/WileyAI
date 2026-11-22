package ru.wildlik.wileyai.mobile;
public final class ChatReadinessProbe {
 static void check(boolean value){if(!value)throw new AssertionError();}
 static ChatReadiness.Facts facts(ChatReadiness.State speech,ChatReadiness.State wake,ChatReadiness.State model,ChatReadiness.Source source,ChatReadiness.State pc){return new ChatReadiness.Facts(speech,wake,speech,model,source,ChatReadiness.source(source,model,pc,ChatReadiness.State.UNKNOWN),pc);}
 public static void main(String[] args){
  var ready=ChatReadiness.State.READY;var setup=ChatReadiness.State.SETUP_REQUIRED;var unknown=ChatReadiness.State.UNKNOWN;var wait=ChatReadiness.State.CHECKING;var unavail=ChatReadiness.State.UNAVAILABLE;var error=ChatReadiness.State.ERROR;
  check(ChatReadiness.asset(false,false,false,false)==wait); check(ChatReadiness.asset(true,true,false,false)==wait);
  check(ChatReadiness.asset(true,false,true,false)==unknown);check(ChatReadiness.asset(true,false,false,false)==setup);check(ChatReadiness.asset(true,false,false,true)==error);
  check(ChatReadiness.hint(facts(ready,ready,ready,ChatReadiness.Source.LOCAL,unknown))==ChatReadiness.Hint.NONE);
  check(ChatReadiness.hint(facts(ready,ready,setup,ChatReadiness.Source.LOCAL,unknown))==ChatReadiness.Hint.MODEL);
  check(ChatReadiness.hint(facts(ready,ready,wait,ChatReadiness.Source.LOCAL,unknown))==ChatReadiness.Hint.NONE);
  check(ChatReadiness.hint(facts(unavail,ready,ready,ChatReadiness.Source.LOCAL,unknown))==ChatReadiness.Hint.SPEECH_CHECK);
  check(ChatReadiness.hint(facts(ready,ready,error,ChatReadiness.Source.LOCAL,unknown))==ChatReadiness.Hint.MODEL_CHECK);
  check(ChatReadiness.hint(facts(setup,setup,ready,ChatReadiness.Source.LOCAL,unknown))==ChatReadiness.Hint.SPEECH);
  check(ChatReadiness.selectedSpeech(3,setup,unknown,unavail)==unknown);
  check(ChatReadiness.hint(facts(unknown,setup,ready,ChatReadiness.Source.LOCAL,unknown))==ChatReadiness.Hint.NONE);
  check(ChatReadiness.hint(facts(ready,ready,setup,ChatReadiness.Source.CLOUD,unknown))==ChatReadiness.Hint.NONE);
  check(ChatReadiness.hint(facts(ready,ready,ready,ChatReadiness.Source.PC,unavail))==ChatReadiness.Hint.PC);
  check(ChatReadiness.hint(facts(wait,wait,wait,ChatReadiness.Source.LOCAL,wait))==ChatReadiness.Hint.NONE);
  check(ChatReadiness.manualVoice(true,false,ready,ready)==setup);
  check(ChatReadiness.manualVoice(false,true,ready,unavail)==unavail);
 }
}
