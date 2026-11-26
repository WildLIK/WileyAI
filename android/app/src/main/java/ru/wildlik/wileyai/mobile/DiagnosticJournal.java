package ru.wildlik.wileyai.mobile;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
/** Allowlisted events and integer measurements only; caller data is never accepted. */
final class DiagnosticJournal {
 enum Event { SESSION_START,SESSION_STOP,APP_OPEN,APP_BACKGROUND,SCREEN_CHAT,SCREEN_COMPONENTS,SCREEN_COMMANDS,SCREEN_SETTINGS,SCREEN_OTHER,SCREEN_OPEN_MS,VOICE_BEGIN,VOICE_TURN_BEGIN,VOICE_END,VOICE_WAKE,WAKE_START,WAKE_READY,WAKE_READ_SAMPLES,WAKE_DECODER_FINALS,WAKE_REJECTED_FINALS,WAKE_STOP_REASON,WAKE_DETECTION_LAG_MS,WAKE_DETECTION_SAMPLE,PCM_BOUNDARY_SAMPLE,PCM_BUFFERED_SAMPLES,PCM_PEAK_BUFFER_SAMPLES,PCM_DELIVERED_SAMPLES,PCM_ACCEPTED_SAMPLES,PCM_OVERFLOW_SAMPLES,PCM_DISCARDED_SAMPLES,AUDIO_RECORD_COUNT,GIGA_CAPTURE_MS,GIGA_VAD_DISCARDED_SAMPLES,GIGA_LIMIT_DISCARDED_SAMPLES,GIGA_AUDIO_MS,GIGA_DECODE_MS,GIGA_QUEUE_MS,VOICE_WINDOW_SHOW,VOICE_WINDOW_HIDE,VOICE_UI_STATE,VOICE_LEVEL_MILLI,VOICE_STT,VOICE_STT_RESULT,MANUAL_STT_BEGIN,MANUAL_STT_RESULT,MANUAL_STT_MS,MANUAL_STT_ERROR,MANUAL_STT_END,VOICE_ROUTE,VOICE_ANSWER,VOICE_TTS,VOICE_ERROR,MODEL_BEGIN,MODEL_DONE,MODEL_ERROR,MODEL_CANCEL,MODEL_OUTCOME,MODEL_STOP_REASON,MODEL_USER_DECLINED,MODEL_COLD,MODEL_LOAD_MS,MODEL_CONTEXT_MS,MODEL_PROMPT_MS,MODEL_QUEUE_MS,MODEL_TOKENIZE_MS,MODEL_PREFILL_MS,MODEL_DECODE_MS,MODEL_FIRST_MS,MODEL_GENERATION_MS,MODEL_TOTAL_MS,MODEL_RAM_BEFORE_MB,MODEL_RAM_AFTER_MB,APP_SEARCH,APP_CANDIDATES,PERMISSION_DECISION,ACTION_RESULT,UI_ERROR, TURN_BEGIN_MS, TURN_SPEECH_END_MS, TURN_STT_DONE_MS, TURN_INTENT_MS, TURN_INTENT, TURN_ROUTE_MS, TURN_ROUTE, TURN_MODEL_BEGIN_MS, TURN_MODEL_FIRST_MS, TURN_TTS_SYNTHESIS_MS, TURN_TTS_PLAY_START_MS, TURN_ENDPOINT_MS, TURN_PCM_DRAINED_MS, TURN_STT_SUBMIT_MS, TURN_STT_QUEUE_DURATION_MS, TURN_STT_DECODE_DURATION_MS, TURN_STT_TEXT_READY_MS, TURN_COMMAND_TEXT_MS, TURN_REPLY_READY_MS, TURN_TTS_PREPARE_MS, TURN_TTS_SUBMIT_MS, TURN_TTS_FIRST_AUDIO_MS, WAKE_CANDIDATE_AT_MS, WAKE_CANDIDATE_VARIANT, WAKE_CANDIDATE_CONF_MILLI, WAKE_CANDIDATE_LAG_MS, WAKE_CANDIDATE_FINAL, WAKE_SERVICE_STATE, WAKE_WINDOW_LATENCY_MS, WAKE_WINDOW_OUTCOME, WAKE_TURN_LINK, WAKE_RESULT, WAKE_FALSE_MARK, WAKE_PREFIX_ENABLED, WAKE_PREFIX_RECOVERY_US, WAKE_GIGA_HANDOFF_MS }
 static final int MAX_BYTES=5*1024*1024; static final long RETENTION_MS=7L*24*60*60*1000;
 private static final int ROTATE_TO_BYTES = MAX_BYTES - 64 * 1024;
 private final Path file; private long knownSize=-1; private long lastPrune;
 private long retentionMs=RETENTION_MS;
 DiagnosticJournal(Path file){this.file=file;}
 synchronized void setRetentionDays(int days){retentionMs=days*24L*60*60*1000;lastPrune=0;}
 synchronized void append(long time,long session,Event event,long value)throws IOException {
  append(time,session,event,value,0);
 }
 synchronized void append(long time,long session,Event event,long value,long turn)throws IOException {
  byte[] line=(time+"|"+session+"|"+event.name()+"|"+value+(turn==0?"":"|"+turn)+"\n").getBytes(StandardCharsets.UTF_8);
  long actual=Files.exists(file)?Files.size(file):0;
  boolean full=actual+line.length>MAX_BYTES;
  if(knownSize!=actual || time-lastPrune>60*60*1000L || full){
   List<String> lines=valid(time);trim(lines, full ? ROTATE_TO_BYTES : MAX_BYTES-line.length);write(lines);lastPrune=time;
  }
  Files.createDirectories(file.getParent());
  Files.write(file,line,StandardOpenOption.CREATE,StandardOpenOption.APPEND);
  knownSize += line.length;
 }
 synchronized List<String> read(long now)throws IOException {List<String> lines=valid(now);trim(lines,MAX_BYTES);write(lines);return lines;}
 synchronized void clear()throws IOException {Files.deleteIfExists(file);Files.deleteIfExists(file.resolveSibling(file.getFileName()+".tmp"));knownSize=0;}
 synchronized long size()throws IOException {return Files.exists(file)?Files.size(file):0;}
 /** The last service-accepted wake, even after process restart. Serialized with export and append. */
 synchronized int markLastWakeFalse(long now,long session)throws IOException {
  long wake=0;Set<Long> labels=new HashSet<>();
  for(String row:valid(now)){
   String[] v=row.split("\\|",-1);
   if(v.length!=5)continue;
   if(v[2].equals(Event.VOICE_WAKE.name()))wake=Long.parseLong(v[4]);
   if(v[2].equals(Event.WAKE_FALSE_MARK.name()))labels.add(Long.parseLong(v[4]));
  }
  if(wake==0)return 0;
  if(labels.contains(wake))return 2;
  append(now,session,Event.WAKE_FALSE_MARK,1,wake);
  return 1;
 }
 private List<String> valid(long now)throws IOException {
  if(!Files.exists(file))return new ArrayList<>();
  if(Files.size(file)>MAX_BYTES*2L){Files.delete(file);return new ArrayList<>();}
  List<String> out=new ArrayList<>();for(String line:Files.readAllLines(file,StandardCharsets.UTF_8)){
   String[] p=line.split("\\|",-1);if(p.length!=4&&p.length!=5)continue;
   try {long time=Long.parseLong(p[0]);Long.parseLong(p[1]);Event.valueOf(p[2]);Long.parseLong(p[3]);if(p.length==5&&Long.parseLong(p[4])<=0)continue;if(time<=now+60000 && time>=now-retentionMs)out.add(line);}catch(Exception ignored){}
  }return out;
 }
 private void trim(List<String> lines,int limit){int sep=System.lineSeparator().getBytes(StandardCharsets.UTF_8).length,bytes=0,cut=0;for(String line:lines)bytes+=line.getBytes(StandardCharsets.UTF_8).length+sep;while(bytes>limit&&cut<lines.size()){bytes-=lines.get(cut++).getBytes(StandardCharsets.UTF_8).length+sep;}if(cut>0)lines.subList(0,cut).clear();}
 private void write(List<String> lines)throws IOException {Files.createDirectories(file.getParent());Path temp=file.resolveSibling(file.getFileName()+".tmp");Files.write(temp,lines,StandardCharsets.UTF_8);try{Files.move(temp,file,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);}catch(AtomicMoveNotSupportedException x){Files.move(temp,file,StandardCopyOption.REPLACE_EXISTING);}knownSize=Files.size(file);}
}
