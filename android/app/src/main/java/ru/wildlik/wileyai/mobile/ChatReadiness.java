package ru.wildlik.wileyai.mobile;

/** Read-only UI facts. Installed assets and configured endpoints are not runtime health checks. */
final class ChatReadiness {
 enum State { READY, SETUP_REQUIRED, CHECKING, UNAVAILABLE, ERROR, UNKNOWN }
 enum Source { LOCAL, PC, CLOUD, GATEWAY, ACCOUNT }
 enum Hint { NONE, SPEECH, SPEECH_CHECK, MODEL, MODEL_CHECK, PC }
 record Facts(State manualVoice, State wake, State commandSpeech, State localModel, Source source, State sourceState, State pc) {}
 static State asset(boolean checked, boolean busy, boolean installed, boolean error) {
  if (busy || !checked) return State.CHECKING;
  if (error) return State.ERROR;
  return installed ? State.UNKNOWN : State.SETUP_REQUIRED;
 }
 static State selectedSpeech(int engine, State vosk, State giga, State androidSpeech) {
  return engine == 0 ? vosk : engine == 3 ? giga : androidSpeech;
 }
 static State manualVoice(boolean localTarget, boolean micPermission, State selectedSpeech, State pc) {
  if (!micPermission) return State.SETUP_REQUIRED;
  return localTarget ? selectedSpeech : pc;
 }
 static State source(Source source, State model, State pc, State cloud) {
  return source == Source.LOCAL ? model : source == Source.PC ? pc : cloud;
 }
 static Hint hint(Facts facts) {
  if(facts.source()==Source.PC && (facts.pc()==State.UNAVAILABLE || facts.pc()==State.SETUP_REQUIRED)) return Hint.PC;
  if(facts.manualVoice()==State.SETUP_REQUIRED) return Hint.SPEECH;
  if(facts.manualVoice()==State.UNAVAILABLE || facts.manualVoice()==State.ERROR) return Hint.SPEECH_CHECK;
  if(facts.source()==Source.LOCAL && facts.localModel()==State.SETUP_REQUIRED) return Hint.MODEL;
  if(facts.source()==Source.LOCAL && facts.localModel()==State.ERROR) return Hint.MODEL_CHECK;
  return Hint.NONE;
 }
 private ChatReadiness() {}
}
