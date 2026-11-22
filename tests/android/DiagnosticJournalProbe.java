package ru.wildlik.wileyai.mobile;
import java.nio.file.*;import java.nio.charset.StandardCharsets;import java.util.*;
public final class DiagnosticJournalProbe {
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args)throws Exception{
  Path path=Path.of(args[0],"diagnostics","events.txt");DiagnosticJournal j=new DiagnosticJournal(path);long now=1800000000000L;
  check(j.size()==0);j.append(now-8L*24*60*60*1000,11,DiagnosticJournal.Event.VOICE_BEGIN,0);j.append(now,12,DiagnosticJournal.Event.VOICE_STT,123);
  var rows=j.read(now);check(rows.size()==1&&rows.get(0).contains("|12|VOICE_STT|123"));
  Files.writeString(path,"token=supersecret\n"+now+"|1|VOICE_STT|password\n"+now+"|1|PRIVATE_MESSAGE|1\n",StandardCharsets.UTF_8);
  j.append(now,13,DiagnosticJournal.Event.VOICE_ERROR,0);String safe=Files.readString(path);check(!safe.contains("token")&&!safe.contains("password")&&!safe.contains("PRIVATE_MESSAGE"));
  String one=now+"|13|VOICE_STT|123456\n";Files.writeString(path,one.repeat(200000),StandardCharsets.UTF_8);j.append(now,13,DiagnosticJournal.Event.MODEL_DONE,45);check(j.size()<=DiagnosticJournal.MAX_BYTES);check(!j.read(now).isEmpty());
  String formatted=DiagnosticFormatter.events(j.read(now));Path exported=Path.of(args[0],"WileyAI_diagnostics_test.txt");Files.writeString(exported,formatted,StandardCharsets.UTF_8);String text=Files.readString(exported,StandardCharsets.UTF_8);check(text.contains("Хронология")&&text.contains("MODEL_DONE")&&text.contains("Итого событий")&&!text.contains("password"));
  j.append(now,14,DiagnosticJournal.Event.WAKE_START,0);j.append(now,14,DiagnosticJournal.Event.WAKE_STOP_REASON,2);
  j.append(now,14,DiagnosticJournal.Event.PCM_BOUNDARY_SAMPLE,16000);j.append(now,14,DiagnosticJournal.Event.PCM_OVERFLOW_SAMPLES,0);
  j.append(now,14,DiagnosticJournal.Event.GIGA_DECODE_MS,123);j.append(now,14,DiagnosticJournal.Event.MODEL_USER_DECLINED,0);j.append(now,14,DiagnosticJournal.Event.MODEL_STOP_REASON,1);
  j.append(now,14,DiagnosticJournal.Event.TURN_MODEL_BEGIN_MS,200,99);
  j.append(now,14,DiagnosticJournal.Event.TURN_MODEL_FIRST_MS,450,99);
  String measurements=DiagnosticFormatter.events(j.read(now));check(measurements.contains("PCM_BOUNDARY_SAMPLE")&&measurements.contains("MODEL_USER_DECLINED")&&measurements.contains("GIGA_DECODE_MS"));
  check(measurements.contains("TURN_MODEL_BEGIN_MS | 200 | 99")&&measurements.contains("TURN_MODEL_FIRST_MS | 450 | 99"));
  check(j.markLastWakeFalse(now,14)==0);
  j.append(now,14,DiagnosticJournal.Event.VOICE_WAKE,0,123);
  // A system window launch and a new but rejected candidate don't change the target.
  j.append(now,14,DiagnosticJournal.Event.VOICE_WINDOW_SHOW,0);
  j.append(now,14,DiagnosticJournal.Event.WAKE_CANDIDATE_FINAL,1,124);
  check(j.markLastWakeFalse(now,14)==1);
  check(new DiagnosticJournal(path).markLastWakeFalse(now,15)==2);
  check(j.read(now).stream().filter(line->line.contains("|WAKE_FALSE_MARK|1|123")).count()==1);
  j.append(now,14,DiagnosticJournal.Event.VOICE_WAKE,0,125);
  check(j.markLastWakeFalse(now,14)==1);
  j.clear();check(j.size()==0&&!Files.exists(path));
 }
}
