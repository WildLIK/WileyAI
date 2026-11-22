package ru.wildlik.wileyai.mobile;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.os.Bundle;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.concurrent.atomic.AtomicReference;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.util.*;
import java.util.zip.*;

/** Explicit, local-only sample collection; the microphone is never started in the background. */
public final class WakeSampleActivity extends Activity {
    private static final int EXPORT=721; private static final int RATE=16000, MAX=50;
    private static final String[] PHRASES={"Вайли","Окей, Вайли","Вайли, привет","Вайли, включи музыку","Вайли, сколько времени"};
    private static final String[] MODES={"обычным голосом","быстро","тихо","с небольшого расстояния","с паузой перед командой","слитно с командой"};
    private static final AtomicReference<WakeSampleActivity> AUDIO_LEASE=new AtomicReference<>();
    private final Object publication=new Object();
    private MobileUi ui;
    private LinearLayout list;
    private TextView status;
    private File dir;
    private boolean testSet,study,exporting;
    private WakeStudySessions sessions;
    private WakeStudySessions.Entry activeSession;
    private volatile AudioRecord recorder;
    private volatile boolean recording,cancelled,finishRequested;
    private volatile int generation;
    private MediaPlayer player;

    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        ui=new MobileUi(this,new SettingsRepository(this).theme());
        testSet=BuildConfig.DEBUG&&getIntent().getBooleanExtra("test_samples",false);
        study=getIntent().getBooleanExtra("study_samples",false);
        dir=new File(study&&testSet?getCacheDir():study?getFilesDir():testSet?getCacheDir():getFilesDir(),
            study?(testSet?"wake-study-test":"wake-study"):(testSet?"wake-training-test":"wake-training"));
        if(study){
            sessions=new WakeStudySessions(dir,samples());
            activeSession=sessions.get(sessions.selected);
            if(activeSession==null&&!sessions.list().isEmpty())activeSession=sessions.list().get(0);
        }
        showScreen();
    }
    private File[] samples(){
        File[] files=dir.listFiles((d,name)->name.endsWith(".json")
                &&WakeSampleStore.validId(name.substring(0,name.length()-5)));
        if(files==null)return new File[0];
        Arrays.sort(files,Comparator.comparing(File::getName));
        return files;
    }
    private void add(LinearLayout box,android.view.View view){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=ui.dp(8);box.addView(view,p);}
    private void showScreen(){
        LinearLayout root=ui.vertical();root.setPadding(ui.dp(16),ui.dp(12),ui.dp(16),ui.dp(16));root.setBackgroundColor(ui.theme.base);
        add(root,ui.text(study?"Исследование голосового вызова":"Обучение голосового вызова",22,ui.theme.text));
        if(testSet)add(root,ui.text("Тестовый набор: отдельное временное хранилище, основные образцы не изменяются.",15,ui.theme.accentText));
        else if(!study&&BuildConfig.DEBUG)add(root,ui.button("Проверить на отдельном тестовом наборе",()->startActivity(new Intent(this,WakeSampleActivity.class).putExtra("test_samples",true))));
        if(!study)add(root,ui.button("Новая запись для исследования",()->startActivity(
            new Intent(this,WakeSampleActivity.class).putExtra("study_samples",true).putExtra("test_samples",testSet))));
        add(root,ui.text("Запись начинается только после вашего согласия. Образцы хранятся на телефоне, не отправляются в сеть и не попадают в диагностический журнал. Их можно прослушать, удалить или экспортировать.",14,ui.theme.secondary));
        status=ui.text("Готово",14,ui.theme.text);add(root,status);
        int n=samples().length;
        if(study){
            add(root,ui.text("Образцов: "+n+" / "+WakeStudy.MAX_CLIPS+" · отдельное хранилище",14,ui.theme.secondary));
            sessions.recount(samples());
            if(activeSession!=null){
                add(root,ui.text(sessionSummary(activeSession),15,ui.theme.text));
                add(root,ui.button("Переименовать сессию",this::renameSession));
                add(root,ui.button("Кто говорит: "+roleLabel(activeSession.role),()->chooseRole(activeSession.role,
                        role->savePreferences(activeSession.title,role,activeSession.label))));
                add(root,ui.button("Что прозвучит: "+WakeStudy.LABELS.get(activeSession.label),()->
                        chooseContent(label->savePreferences(activeSession.title,activeSession.role,label))));
            }
            add(root,ui.button("Выбрать сессию",this::chooseSession));
            add(root,ui.button("Новая сессия",this::configureSession));
        }else add(root,ui.text("Образцов: "+n+" / "+MAX+"\nДалее: «"+PHRASES[n%PHRASES.length]+"» — "+MODES[(n/PHRASES.length)%MODES.length],15,ui.theme.text));
        add(root,ui.button("Начать запись образца",()->consent()));
        if(study)add(root,ui.button("Завершить и сохранить",()->stopCapture(false)));
        add(root,ui.button("Отменить запись",()->stopCapture(true)));
        add(root,ui.button("Экспортировать ZIP",()->export()));
        add(root,ui.button(study?"Удалить записи всех сессий":"Удалить все образцы",()->{if(audioInUse()){status.setText("Сначала завершите запись или воспроизведение.");return;}ui.dialog().setMessage("Удалить все локальные образцы голосового вызова из этого набора?").setNegativeButton("Отмена",null).setPositiveButton("Удалить",(d,w)->{boolean deleted=WakeSampleStore.deleteAll(dir);showScreen();status.setText(deleted?"Образцы удалены.":"Не удалось удалить некоторые файлы. Повторите попытку.");}).show();}));
        list=ui.vertical();
        ScrollView scroll=new ScrollView(this);
        if(study){
            root.addView(list);
            scroll.addView(root);
        }else{
            scroll.addView(list);
            root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        }
        for(File meta:samples())addSample(meta);
        add(root,ui.button("Назад",this::finish));
        setContentView(study?scroll:root);
    }
    private boolean audioInUse(){return recording||exporting||AUDIO_LEASE.get()!=null;}
    private void releaseAudio(){if(AUDIO_LEASE.compareAndSet(this,null))HandsFreeService.resumeExternal();}
    private static String sessionSummary(WakeStudySessions.Entry entry) {
        String last=entry.lastRecorded==0?"Записей пока нет":
            java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT,java.text.DateFormat.SHORT)
                .format(new Date(entry.lastRecorded));
        return entry.displayName()+" · "+entry.session.speaker()+" · "+entry.count+" обр. · "+last;
    }
    private void chooseSession(){
        if(audioInUse())return;
        var options=sessions.list();
        if(options.isEmpty()){status.setText("Создайте первую сессию.");return;}
        String[] captions=options.stream().map(WakeSampleActivity::sessionSummary).toArray(String[]::new);
        ui.dialog().setTitle("Продолжить сессию").setItems(captions,(dialog,which)->{
            var selected=options.get(which);
            try{sessions.select(selected);activeSession=selected;showScreen();}
            catch(IOException failure){status.setText("Не удалось сохранить выбор сессии.");}
        }).setNegativeButton("Отмена",null).show();
    }
    private void renameSession(){
        if(audioInUse()||activeSession==null)return;
        EditText name=new EditText(this);
        name.setSingleLine();name.setText(activeSession.title);name.setHint(activeSession.session.speaker());
        name.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(60)});
        ui.dialog().setTitle("Название сессии").setView(name).setNegativeButton("Отмена",null)
            .setPositiveButton("Сохранить",(d,w)->savePreferences(name.getText().toString().trim(),
                            activeSession.role,activeSession.label)).show();
    }
    private static String roleLabel(String role){return WakeStudy.ROLE_LABELS.get(WakeStudy.ROLES.indexOf(
        WakeStudySessions.validatedRole(role)));}
    private void chooseRole(String current,java.util.function.Consumer<String> action){
        if(audioInUse())return;
        ui.dialog().setTitle("Кто говорит?")
            .setSingleChoiceItems(WakeStudy.ROLE_LABELS.toArray(new String[0]),WakeStudy.ROLES.indexOf(current),
                (d,i)->{d.dismiss();action.accept(WakeStudy.ROLES.get(i));}).setNegativeButton("Отмена",null).show();
    }
    private void chooseContent(java.util.function.IntConsumer action){
        if(audioInUse())return;
        ui.dialog().setTitle("Что прозвучит?").setItems(WakeStudy.CONTENT_LABELS.toArray(new String[0]),(d,i)->{
            if(i==0)ui.dialog().setTitle("Выберите обращение").setItems(WakeStudy.LABELS.subList(0,6).toArray(new String[0]),
                (dialog,label)->action.accept(label)).setNegativeButton("Отмена",null).show();
            else action.accept(WakeStudy.categoryLabel(i));
        }).setNegativeButton("Отмена",null).show();
    }
    private void savePreferences(String title,String role,int label){
        try{sessions.preferences(activeSession,title,role,label);showScreen();}
        catch(IOException failure){status.setText("Не удалось сохранить настройки сессии.");}
    }
    private void configureSession(){
        if(audioInUse())return;
        LinearLayout form=ui.vertical();
        EditText speaker=new EditText(this);
        speaker.setSingleLine();speaker.setHint("Код диктора, например speaker-a");
        var previous=activeSession==null?null:activeSession.session;
        if(previous!=null)speaker.setText(previous.speaker());
        form.addView(speaker);
        Spinner split=choice(form,"Раздел до оценки",new String[]{"Разработка","Валидация","Закрытый тест"},previous==null?0:WakeStudy.SPLITS.indexOf(previous.split()));
        Spinner level=choice(form,"Громкость речи",new String[]{"Обычная","Тихая"},0);
        Spinner distance=choice(form,"Расстояние до телефона",new String[]{"30 см","1 м","2 м","4 м"},1);
        Spinner environment=choice(form,"Условия",new String[]{"Тихая комната","Обычная комната","Эхо","На улице","Фоновый шум"},1);
        ui.dialog().setTitle("Сессия исследования").setView(form).setMessage(
            "Для прежнего диктора оставьте его код. Другому человеку задайте свой код. Для продолжения уже начатой записи выберите существующую сессию.")
            .setNegativeButton("Отмена",null).setPositiveButton("Создать",(d,w)->{
                try{
                    String code=WakeStudy.alias(speaker.getText().toString());
                    String partition=WakeStudy.SPLITS.get(split.getSelectedItemPosition());
                    activeSession=sessions.openOrCreate(WakeStudy.session(code,partition,
                        WakeStudy.LEVELS.get(level.getSelectedItemPosition()),WakeStudy.DISTANCES.get(distance.getSelectedItemPosition()),
                        WakeStudy.ENVIRONMENTS.get(environment.getSelectedItemPosition()),System.currentTimeMillis()));
                    showScreen();status.setText("Сессия выбрана. Проверьте диктора и категорию.");
                }catch(IllegalArgumentException invalid){
                    status.setText("Укажите условный код латиницей. Код диктора используется в одном разделе.");
                }catch(IOException failure){status.setText("Не удалось сохранить сессию.");}
            }).show();
    }
    private Spinner choice(LinearLayout form,String title,String[] labels,int selected){
        form.addView(ui.text(title,14,ui.theme.text));
        Spinner value=new Spinner(this);
        var adapter=new ArrayAdapter<>(this,android.R.layout.simple_spinner_item,labels);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        value.setAdapter(adapter);value.setSelection(selected);form.addView(value);
        return value;
    }
    private void stopCapture(boolean discard){
        if(!recording)return;
        synchronized(publication){
            if(discard)cancelled=true;else finishRequested=true;
        }
        AudioRecord a=recorder;
        if(a!=null)try{a.stop();}catch(IllegalStateException ignored){}
        status.setText(discard?"Запись отменена":"Завершаю запись…");
    }
    private void addSample(File meta){try{
        JSONObject j=new JSONObject(readText(meta));String id=j.getString("id");
        if(!WakeSampleStore.validId(id)||!meta.getName().equals(id+".json"))return;
        File wav=new File(dir,id+".wav");if(!wav.isFile())return;
        LinearLayout row=ui.vertical();
        String details=j.getString("phrase")+" · "+j.getString("condition");
        if(study){
            if(activeSession==null||!activeSession.session.id().equals(j.getString("session_id")))return;
            details+=" · "+j.getString("speaker_id")+" · "+roleLabel(j.optString("speaker_role"))+
                " · Vosk: "+voskLabel(j.getJSONObject("vosk").getString("status"));
        }
        add(row,ui.text(details,14,ui.theme.text));
        if(study){
            add(row,ui.button("Исправить содержание",()->chooseContent(label->editLabel(meta,label,null))));
            add(row,ui.button("Уточнить диктора",()->chooseRole(WakeStudySessions.validatedRole(j.optString("speaker_role")),
                    role->editLabel(meta,null,role))));
        }
        LinearLayout actions=ui.row();Button play=ui.button("Прослушать",()->play(wav));Button remove=ui.button("Удалить",()->{if(audioInUse()){status.setText("Сначала завершите запись или воспроизведение.");return;}ui.dialog().setMessage("Удалить этот образец?").setNegativeButton("Отмена",null).setPositiveButton("Удалить",(d,w)->{boolean deleted=deletePair(meta);showScreen();status.setText(deleted?"Образец удалён.":"Не удалось удалить образец. Повторите попытку.");}).show();});
        actions.addView(play,new LinearLayout.LayoutParams(0,-2,1));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1);p.setMarginStart(ui.dp(8));actions.addView(remove,p);add(row,actions);add(list,row);
    }catch(Exception ignored){}}
    private static String voskLabel(String status){
        return switch(status){case "accepted"->"обнаружено";case "not_detected"->"не обнаружено";default->"недоступно";};
    }
    private void editLabel(File meta,Integer label,String role){
        if(audioInUse())return;
        try{
            JSONObject row=new JSONObject(readText(meta));
            if(label!=null)row.put("label",label).put("kind",WakeStudy.kind(label))
                .put("phrase",WakeStudy.LABELS.get(label)).put("speech_kind",WakeStudy.content(label));
            if(role!=null)row.put("speaker_role",role);
            File temp=File.createTempFile("label-",".tmp",dir);
            try{
                Files.write(temp.toPath(),row.toString().getBytes(StandardCharsets.UTF_8));
                Files.move(temp.toPath(),meta.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            }finally{Files.deleteIfExists(temp.toPath());}
            showScreen();status.setText("Метка исправлена.");
        }catch(Exception error){status.setText("Не удалось изменить метку.");}
    }
    private static String readText(File file)throws IOException{
        if(file.length()>8192)throw new IOException();
        return new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);
    }
    private void consent(){
        if(audioInUse())return;
        if(samples().length>=(study?WakeStudy.MAX_CLIPS:MAX)){status.setText("Достигнут предел набора. Экспортируйте его или удалите ненужные образцы.");return;}
        if(study&&activeSession==null){status.setText("Сначала создайте сессию.");return;}
        if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){status.setText("Для записи разрешите микрофон в настройках Android.");return;}
        if(HandsFreeService.answering()){status.setText("Дождитесь окончания голосового сеанса.");return;}
        int n=samples().length,label=study?activeSession.label:0;
        var session=study?activeSession.session:null;
        String role=study?activeSession.role:"unknown";
        String phrase=study?WakeStudy.LABELS.get(label):PHRASES[n%PHRASES.length];
        String mode=study?session.level()+" · "+session.distanceCm()+" см · "+session.environment():MODES[(n/PHRASES.length)%MODES.length];
        int seconds=study?WakeStudy.limitSeconds(label):4;
        ui.dialog().setTitle("Записать образец?").setMessage("Убедитесь, что все участники согласны на запись. После подтверждения микрофон будет записывать до "+seconds+" с. Метка «"+phrase+"». Запись хранится на телефоне до вашего экспорта.")
            .setNegativeButton("Отмена",null).setPositiveButton("Все согласны. Записать",(d,w)->begin(phrase,mode,label,seconds,session,role)).show();
    }
    private void begin(String phrase,String mode,int label,int seconds,WakeStudy.Session currentSession,String role){
        if(recording||HandsFreeService.answering()||!AUDIO_LEASE.compareAndSet(null,this))return;
        recording=true;cancelled=false;finishRequested=false;int ticket=++generation;
        status.setText("Подготавливаю микрофон…");
        HandsFreeService.pauseExternal(()->{
            if(cancelled||ticket!=generation||isFinishing()||isDestroyed()){recording=false;releaseAudio();return;}
            new Thread(()->capture(ticket,phrase,mode,label,seconds,currentSession,role),"wake-sample").start();
        });
    }
    private void capture(int ticket,String phrase,String mode,int label,int seconds,WakeStudy.Session currentSession,String role){
        AudioRecord a=null;VoiceTelemetry.Capture telemetry=null;String error=null;
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        short[] block=new short[1024];byte[] bytes=new byte[2048];
        int total=0;long recordedAt=System.currentTimeMillis();
        try{
            if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED)throw new SecurityException();
            int min=AudioRecord.getMinBufferSize(RATE,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);
            if(min<=0)throw new IOException();
            a=new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,RATE,AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,Math.max(min*2,8192));recorder=a;
            if(cancelled||finishRequested||a.getState()!=AudioRecord.STATE_INITIALIZED)throw new IOException();
            a.startRecording();
            if(a.getRecordingState()!=AudioRecord.RECORDSTATE_RECORDING)throw new IOException();
            telemetry=VoiceTelemetry.captureOpened(VoiceTelemetry.SAMPLE);
            DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());
            runOnUiThread(()->{if(ticket==generation&&!cancelled&&!finishRequested)status.setText("Идёт запись — говорите сейчас");});
            while(!cancelled&&!finishRequested&&total<RATE*seconds){
                int count=a.read(block,0,Math.min(block.length,RATE*seconds-total));
                if(count<=0){if(cancelled||finishRequested)break;throw new IOException();}
                for(int i=0;i<count;i++){bytes[i*2]=(byte)block[i];bytes[i*2+1]=(byte)(block[i]>>8);}
                out.write(bytes,0,count*2);total+=count;
            }
        }catch(Exception e){if(!cancelled&&!finishRequested)error="Не удалось записать образец. Проверьте микрофон.";}
        finally{
            if(a!=null){try{a.stop();}catch(IllegalStateException ignored){}a.release();}
            if(telemetry!=null){telemetry.close();DiagnosticLog.event(DiagnosticJournal.Event.AUDIO_RECORD_COUNT,VoiceTelemetry.snapshot().captureCount());}
            recorder=null;
        }
        try{
            if(!cancelled&&error==null){
                if(total<(study?WakeStudy.MIN_SAMPLES:1))error="Запись слишком короткая.";
                else{
                    byte[] raw=out.toByteArray();
                    try{
                        JSONObject measured=null;
                        if(study){
                            runOnUiThread(()->{
                                releaseAudio();
                                if(ticket==generation&&!cancelled)status.setText("Проверяю запись локальным Vosk…");
                            });
                            String preset=new SettingsRepository(this).preferences.getString("wake_phrase",WakeSettings.defaultPhrase(this));
                            if(!WakePhrase.valid(preset))preset=WakePhrase.DEFAULT;
                            measured=WakeSampleVosk.evaluate(this,raw,preset,()->cancelled||ticket!=generation);
                        }
                        save(ticket,raw,phrase,mode,label,currentSession,recordedAt,measured,role);
                    }finally{Arrays.fill(raw,(byte)0);}
                }
            }
        }catch(Exception write){error="Не удалось сохранить образец.";}
        finally{
            Arrays.fill(block,(short)0);Arrays.fill(bytes,(byte)0);
            String outcome=error;
            runOnUiThread(()->{
                recording=false;releaseAudio();
                if(ticket==generation&&!isFinishing()&&!isDestroyed()){
                    showScreen();status.setText(cancelled?"Запись отменена":outcome==null?"Образец сохранён локально.":outcome);
                }
            });
        }
    }
    private void save(int ticket,byte[] raw,String phrase,String mode,int label,WakeStudy.Session studySession,long recordedAt,JSONObject measured,String role)throws Exception{
        if(cancelled||ticket!=generation)return;
        if(!dir.isDirectory()&&!dir.mkdirs())throw new IOException();
        String id=UUID.randomUUID().toString();
        File wav=new File(dir,id+".wav"),meta=new File(dir,id+".json");
        File audioTemp=new File(dir,id+".wav.tmp"),metaTemp=new File(dir,id+".json.tmp");
        try{
            try(OutputStream out=new FileOutputStream(audioTemp)){out.write(wavHeader(raw.length));out.write(raw);}
            JSONObject row=new JSONObject().put("id",id).put("phrase",phrase).put("condition",mode).put("sample_rate",RATE)
                .put("channels",1).put("format","pcm_s16le");
            if(studySession!=null)row.put("schema",1).put("label",label).put("kind",WakeStudy.kind(label))
                .put("speaker_role",role).put("speech_kind",WakeStudy.content(label)).put("speaker_id",studySession.speaker())
                .put("session_id",studySession.id()).put("split",studySession.split()).put("voice_level",studySession.level())
                .put("distance_cm",studySession.distanceCm()).put("environment",studySession.environment())
                .put("started_at_ms",studySession.started()).put("recorded_at_ms",recordedAt).put("samples",raw.length/2).put("vosk",measured);
            Files.write(metaTemp.toPath(),row.toString().getBytes(StandardCharsets.UTF_8));
            synchronized(publication){
                if(cancelled||ticket!=generation)return;
                Files.move(audioTemp.toPath(),wav.toPath(),StandardCopyOption.ATOMIC_MOVE);
                try{Files.move(metaTemp.toPath(),meta.toPath(),StandardCopyOption.ATOMIC_MOVE);}
                catch(IOException error){Files.deleteIfExists(wav.toPath());throw error;}
            }
        }finally{Files.deleteIfExists(audioTemp.toPath());Files.deleteIfExists(metaTemp.toPath());}
    }
    static byte[] wavHeader(int bytes){byte[] h=new byte[44];System.arraycopy(new byte[]{'R','I','F','F'},0,h,0,4);put(h,4,36+bytes,4);System.arraycopy(new byte[]{'W','A','V','E','f','m','t',' '},0,h,8,8);put(h,16,16,4);put(h,20,1,2);put(h,22,1,2);put(h,24,RATE,4);put(h,28,RATE*2,4);put(h,32,2,2);put(h,34,16,2);System.arraycopy(new byte[]{'d','a','t','a'},0,h,36,4);put(h,40,bytes,4);return h;}
    private static void put(byte[] a,int pos,int value,int count){for(int i=0;i<count;i++)a[pos+i]=(byte)(value>>(8*i));}
    private boolean deletePair(File meta){try{JSONObject j=new JSONObject(readText(meta));String id=j.getString("id");if(!meta.getName().equals(id+".json"))return false;return WakeSampleStore.deletePair(dir,id);}catch(Exception ignored){return false;}}
    private void play(File wav){
        if(audioInUse()||HandsFreeService.answering()||!AUDIO_LEASE.compareAndSet(null,this))return;
        int ticket=++generation;
        status.setText("Подготавливаю воспроизведение…");
        HandsFreeService.pauseExternal(()->{
            if(ticket!=generation||isFinishing()||isDestroyed()){releaseAudio();return;}
            try{
                MediaPlayer m=new MediaPlayer();player=m;
                m.setDataSource(wav.getAbsolutePath());
                m.setOnCompletionListener(x->stopPlayer());
                m.setOnErrorListener((x,what,extra)->{stopPlayer();return true;});
                m.prepare();m.start();status.setText("Воспроизвожу образец");
            }catch(Exception e){stopPlayer();releaseAudio();status.setText("Не удалось прослушать образец.");}
        });
    }
    private void stopPlayer(){
        MediaPlayer p=player;player=null;
        if(p==null)return;
        try{p.stop();}catch(IllegalStateException ignored){}
        p.release();releaseAudio();if(status!=null)status.setText("Готово");
    }
    private void export(){
        if(audioInUse()||samples().length==0){status.setText("Сначала завершите запись и запишите хотя бы один образец.");return;}
        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
            .setType("application/zip").putExtra(Intent.EXTRA_TITLE,study?"WileyAI-wake-study.zip":"WileyAI-wake-samples.zip");
        if(study)intent.putExtra(Intent.EXTRA_LOCAL_ONLY,true);
        try{startActivityForResult(intent,EXPORT);}catch(Exception e){status.setText("Не удалось открыть сохранение файла.");}
    }
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(request!=EXPORT||result!=RESULT_OK||data==null||data.getData()==null)return;
        android.net.Uri uri=data.getData();
        exporting=true;
        status.setText("Экспортирую образцы…");
        new Thread(()->{
            String outcome="Образцы экспортированы.";
            try(OutputStream stream=getContentResolver().openOutputStream(uri);ZipOutputStream zip=new ZipOutputStream(stream)){
                StringBuilder manifest=new StringBuilder(WakeStudy.EXPORT_HEADER).append('\n');
                for(File meta:samples()){
                    JSONObject row=new JSONObject(readText(meta));
                    String id=row.getString("id");
                    File wav=new File(dir,id+".wav");
                    if(!WakeSampleStore.validId(id)||!meta.getName().equals(id+".json")||!wav.isFile())continue;
                    if(study){
                        WakeStudy.Session fields=WakeStudySessions.fields(row);
                        var entry=sessions.get(fields.id());
                        manifest.append(WakeStudy.row(id,fields,row.getInt("label"),row.getJSONObject("vosk").getString("status"),row.getInt("samples")))
                            .append(',').append(WakeStudy.quote(row.optString("speaker_role")))
                            .append(',').append(WakeStudy.quote(row.optString("speech_kind")))
                            .append(',').append(WakeStudy.quote(entry==null?"":entry.title)).append('\n');
                    }
                    for(File file:new File[]{meta,wav}){
                        zip.putNextEntry(new ZipEntry(file.getName()));
                        try(InputStream in=new FileInputStream(file)){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)zip.write(b,0,n);}
                        zip.closeEntry();
                    }
                }
                if(study){zip.putNextEntry(new ZipEntry("manifest.csv"));zip.write(manifest.toString().getBytes(StandardCharsets.UTF_8));zip.closeEntry();}
            }catch(Exception e){outcome="Не удалось экспортировать образцы.";}
            String msg=outcome;runOnUiThread(()->{
                exporting=false;
                if(!isFinishing()&&!isDestroyed())status.setText(msg);
            });
        },"wake-sample-export").start();
    }
    @Override protected void onPause(){
        synchronized(publication){generation++;cancelled=true;}
        AudioRecord a=recorder;if(a!=null)try{a.stop();}catch(IllegalStateException ignored){}
        stopPlayer();super.onPause();
    }
}
