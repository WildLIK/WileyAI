package ru.wildlik.wileyai.mobile;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.system.Os;
import android.system.OsConstants;
import java.nio.file.Path;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Local-only, fixed vocabulary. No arbitrary messages, paths, app names or text. */
final class DiagnosticLog {
 private static final String PREF="wiley-diagnostics", ENABLED="enabled";
 private static final ExecutorService IO=Executors.newSingleThreadExecutor();
 private static DiagnosticJournal activeJournal; private static volatile long lastEvent; private static volatile Context app; private static volatile boolean enabled, writeFailed; private static volatile long session;
 private static long sessionId(){return java.util.concurrent.ThreadLocalRandom.current().nextLong(1,Long.MAX_VALUE);}
 static void initialize(Context context){
  app=context.getApplicationContext();enabled=app.getSharedPreferences(PREF,0).getBoolean(ENABLED,true);session=sessionId();activeJournal=new DiagnosticJournal(app.getFilesDir().toPath().resolve("diagnostics/events.txt"));if(enabled && startedAt()==0)app.getSharedPreferences(PREF,0).edit().putLong("started_at",System.currentTimeMillis()).apply();
  VoiceDiagnostics.setSink((kind,value)->{DiagnosticJournal.Event e=switch(kind){case 0->DiagnosticJournal.Event.VOICE_TURN_BEGIN;case 1->DiagnosticJournal.Event.VOICE_STT;case 2->DiagnosticJournal.Event.VOICE_ROUTE;case 3->DiagnosticJournal.Event.VOICE_ANSWER;case 4->DiagnosticJournal.Event.VOICE_TTS;case 6->DiagnosticJournal.Event.VOICE_STT_RESULT;default->DiagnosticJournal.Event.VOICE_ERROR;};event(e,value);});
 }
 static long lastEvent(){return lastEvent;}
 static long stoppedAt(){return app==null?0:app.getSharedPreferences(PREF,0).getLong("stopped_at",0);}
 static long startedAt(){return app==null?0:app.getSharedPreferences(PREF,0).getLong("started_at",0);}
 static boolean enabled(){return enabled;}
 static List<String> acousticRows()throws java.io.IOException{
  DiagnosticJournal j=activeJournal;return j==null?List.of():j.read(System.currentTimeMillis());
 }
 private static DiagnosticJournal journal(Context c){return activeJournal;}
 static void start(){if(app==null||enabled)return;writeFailed=false;session=sessionId();app.getSharedPreferences(PREF,0).edit().putBoolean(ENABLED,true).putLong("started_at",System.currentTimeMillis()).putLong("stopped_at",0).apply();enabled=true;event(DiagnosticJournal.Event.SESSION_START,0);}
 static void stop(){if(app==null||!enabled)return;event(DiagnosticJournal.Event.SESSION_STOP,0);enabled=false;app.getSharedPreferences(PREF,0).edit().putBoolean(ENABLED,false).putLong("stopped_at",System.currentTimeMillis()).apply();}
 static void event(DiagnosticJournal.Event event,long value){event(event,value,0);}
 static void event(DiagnosticJournal.Event event,long value,long turn){if(!enabled()||app==null)return;Context c=app;long stamp=System.currentTimeMillis(),id=session;lastEvent=stamp;boolean sampleIndex=event==DiagnosticJournal.Event.WAKE_TURN_LINK||event==DiagnosticJournal.Event.WAKE_CANDIDATE_AT_MS||event==DiagnosticJournal.Event.WAKE_DETECTION_SAMPLE||event==DiagnosticJournal.Event.PCM_BOUNDARY_SAMPLE;long safe=Math.max(-1,sampleIndex?value:Math.min(value,1000000000L));IO.execute(()->{try{journal(c).append(stamp,id,event,safe,turn);}catch(Exception ignored){writeFailed=true;}});}
 static void clear(Runnable finished){Context c=app;if(c==null)return;IO.execute(()->{try{journal(c).clear();java.nio.file.Files.deleteIfExists(c.getCacheDir().toPath().resolve("wileyai-diagnostic-share.txt"));lastEvent=0;writeFailed=false;}catch(Exception ignored){writeFailed=true;}new Handler(Looper.getMainLooper()).post(finished);});}
 static void preview(Consumer<String> done){Context c=app;if(c==null)return;IO.execute(()->{String text;try{text=report(c);}catch(Exception e){text="Не удалось подготовить журнал. Попробуйте ещё раз.";}String value=text;new Handler(Looper.getMainLooper()).post(()->done.accept(value));});}
 static void markLastWakeFalse(Consumer<String> done){
  Context c=app;
  if(c==null||!enabled()){done.accept("Включите диагностику для записи отметок о пробуждении.");return;}
  IO.execute(()->{
   String text;
   try{int result=journal(c).markLastWakeFalse(System.currentTimeMillis(),session);
    if(result==1)lastEvent=System.currentTimeMillis();
    text=switch(result){case 1->"Последнее пробуждение отмечено.";case 2->"Последнее пробуждение уже отмечено.";default->"В журнале пока нет пробуждения с идентификатором.";};
   }catch(Exception error){writeFailed=true;text="Не удалось сохранить отметку.";}
   String message=text;new Handler(Looper.getMainLooper()).post(()->done.accept(message));
  });
 }
 private static String safe(String input){if(input==null)return "неизвестно";String clean=input.replaceAll("[^\\p{L}\\p{N} ._+-]","_");return clean.substring(0,Math.min(80,clean.length()));}
 private static String report(Context c)throws Exception{
  long now=System.currentTimeMillis();DiagnosticJournal j=journal(c);List<String> lines=j.read(now);long bytes=j.size();if(!lines.isEmpty()){try{lastEvent=Long.parseLong(lines.get(lines.size()-1).split("\\|")[0]);}catch(Exception ignored){}}
  android.content.SharedPreferences p=c.getSharedPreferences("wiley-mobile",0);
  ActivityManager.MemoryInfo mem=new ActivityManager.MemoryInfo();((ActivityManager)c.getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(mem);
  long page=-1;try{page=Os.sysconf(OsConstants._SC_PAGESIZE);}catch(Exception ignored){}
  boolean mic=c.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED;
  boolean notifications=((NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE)).areNotificationsEnabled();
  boolean role=false,access=false;try{role=WileyVoiceService.selected(c);access=ScreenObservationService.enabled(c);}catch(Exception ignored){}
  String speech=switch(p.getInt("asr_engine",0)){case 1->"Android";case 2->"Android on-device";case 3->"GigaAM v3";default->"Vosk";};
  String source=p.getBoolean("gateway_enabled",false)?"Gateway":p.getBoolean("account_enabled",false)?"account":p.getBoolean("cloud_enabled",false)?"cloud":"local";
  boolean vosk=false,giga=false,llm=false;long llmMiB=-1;try{vosk=VerifiedModelInstaller.active(c.getFilesDir().toPath().resolve("speech-models"))!=null;}catch(Exception ignored){}try{giga=GigaAmModelManager.activeModel(c)!=null;}catch(Exception ignored){}try{Path file=LlmModels.readActive(c.getFilesDir().toPath().resolve("llm-models"));llm=file!=null;if(llm)llmMiB=java.nio.file.Files.size(file)/1048576;}catch(Exception ignored){}
  StringBuilder out=new StringBuilder("WileyAI — диагностический журнал\nСхема: 3\nЭкспорт UTC: "+Instant.ofEpochMilli(now)+"\n");
  out.append("Устройство: ").append(safe(Build.MANUFACTURER)).append(" / ").append(safe(Build.MODEL)).append("\nAndroid: ").append(safe(Build.VERSION.RELEASE)).append(" API ").append(Build.VERSION.SDK_INT).append("\nABI: ");for(String abi:Build.SUPPORTED_ABIS)out.append(safe(abi)).append(' ');
  out.append("\nСтраница памяти, байт: ").append(page<0?"недоступно":Long.toString(page)).append("\nДоступно RAM, МиБ: ").append(mem.availMem/1048576).append("\nЭнергосбережение: ").append(((PowerManager)c.getSystemService(Context.POWER_SERVICE)).isPowerSaveMode()).append("\n");
  VoiceTelemetry.Snapshot voice=VoiceTelemetry.snapshot();
  out.append("WileyAI: ").append(BuildConfig.VERSION_NAME).append(" code ").append(BuildConfig.VERSION_CODE).append("\nSTT: ").append(speech).append("; Vosk установлен: ").append(vosk).append("; GigaAM установлен: ").append(giga).append("\nLLM Qwen файл: ").append(llm).append("; размер МиБ: ").append(llmMiB<0?"неизвестно":Long.toString(llmMiB)).append("; источник: ").append(source).append("\nTTS: ").append(p.getString("offline_engine","").isEmpty()?"системный":"выбранный движок").append("\nФоновый вызов — настройка: ").append(p.getBoolean("handsfree_enabled",false)).append("; служба в процессе приложения: ").append(HandsFreeService.running()).append("; WakeEngine запущен: ").append(voice.wakeRunning()).append("; захват WakeEngine активен: ").append(voice.wakeCaptureActive()).append("; активных AudioRecord WileyAI: ").append(voice.captureCount()).append("; фраза вызова: ").append(WakePhrase.label(p.getString("wake_phrase",WakeSettings.defaultPhrase(c)))).append("\nРазрешение микрофона: ").append(mic).append("; уведомления: ").append(notifications).append("; роль помощника: ").append(role).append("; служба Accessibility включена: ").append(access).append("\n");
  out.append("Запись: ").append(enabled()?"включена":"остановлена").append("; журнал, байт: ").append(bytes).append("; событий: ").append(lines.size()).append("\n");
  out.append(DiagnosticFormatter.events(lines));
  out.append("\nОбозначения: VOICE_BEGIN — сеанс, VOICE_TURN_BEGIN — реплика; журналы старых версий могли дублировать VOICE_BEGIN. WAKE_READ_SAMPLES, WAKE_DECODER_FINALS, WAKE_REJECTED_FINALS — агрегаты за примерно 5 секунд без текста и аудио. WAKE_STOP_REASON: 1 остановлен, 2 обнаружено, 3 разрешение, 4 ошибка, 5 память, 6 модель/словарь, 7 аудиозахват/декодер. WAKE_DETECTION_LAG_MS — от конца слова по оценке Vosk до получения результата, не измерение фактического конца речи. PCM_* — счётчики передачи, overflow и отброшенная при закрытии очередь; потери драйвера/железа не измеряются. AUDIO_RECORD_COUNT — активные экземпляры AudioRecord WileyAI, без системного распознавателя и MediaRecorder. GIGA_CAPTURE_MS — время сбора после готовности, GIGA_AUDIO_MS — длина поданного аудио, GIGA_DECODE_MS — вычисление модели, GIGA_QUEUE_MS — очередь; GIGA_VAD_DISCARDED_SAMPLES — намеренно отброшенная тишина, GIGA_LIMIT_DISCARDED_SAMPLES — ограничение буфера. MODEL_FIRST_MS — от постановки запроса до первого непустого фрагмента; MODEL_OUTCOME: 0 завершено, 1 остановлено, 2 ошибка; MODEL_STOP_REASON: 1 запрос остановки, 2 таймаут, 3 смена модели/жизненный цикл; MODEL_USER_DECLINED — отклонён план, MODEL_CANCEL — нажата остановка в чате. VOICE_LEVEL_MILLI — нормализованный уровень, не исходный RMS. ACTION_RESULT: 1 подтверждено, 2 не подтверждено/запрошено, 3 отменено, 0 другое.\n");
  out.append("\nTURN_*: этапы связаны ID реплики; _MS — от начала реплики по монотонным часам, _DURATION_MS — отдельная длительность. FIRST_AUDIO — первый непустой буфер синтезатора. TURN_INTENT: 1 локальная команда, 2 план, 3 вопрос. TURN_ROUTE: 1 без модели, 2 быстрая локальная, 3 выбранная модель в автомаршруте, 4 ручной источник. TURN_SPEECH_END_MS — оценка VAD или граница распознавателя. TURN_MODEL_FIRST_MS — первый фрагмент потока; для буферизованных API отсутствует. TURN_TTS_PLAY_START_MS — сигнал Android TTS, без измерения динамика.\n");
  out.append("\nДля WAKE_CANDIDATE_*, WAKE_FALSE_MARK и других связанных с вызовом строк последний столбец — ID пробуждения. WAKE_CANDIDATE_FINAL: 1 обычный финал Vosk, 2 финал с просьбой о разговоре; WAKE_CANDIDATE_VARIANT: 1 Вайли, 2 Уайли, 3 Вай Ли, 4–6 Окей с Уайли, Вай Ли или Вайли соответственно, 7–8 альтернативные фразы. CONF_MILLI — минимум уверенности слов Vosk. WAKE_SERVICE_STATE — биты: 1 служба, 2 окно занято, 4 TTS, 8 внешняя запись, 16 ограниченный экран. WAKE_WINDOW_OUTCOME: 1 принято окном, 2 истёк срок, 3 отказ Android, 4 отмена, 5 занято. WAKE_TURN_LINK связывает ID пробуждения (последний столбец) с ID реплики (значение). WAKE_RESULT: 1 пустой STT, 2 прямой маршрут, 3 модельный маршрут, 4 отклонённая или неполная команда, 5 ошибка STT, 6 ответ готов, 7 остаток имени, ожидание команды. WAKE_FALSE_MARK — ручная отметка владельца.\n");
  if(writeFailed)out.append("\nПРЕДУПРЕЖДЕНИЕ: не удалось записать или очистить некоторые события.\n");
  out.append("\nНедоступно или не проверялось: аудио, текст, названия приложений, содержимое экрана; сырые RMS/VAD и значения по кадрам (VOICE_LEVEL_MILLI — нормализованный уровень 0–1000), акустическое начало звука, FPS и часть причин отказа не инструментированы. Файл не отправляется автоматически.\n");return out.toString();
 }
 private DiagnosticLog(){}
}
