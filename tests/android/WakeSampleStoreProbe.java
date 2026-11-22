package ru.wildlik.wileyai.mobile;

import java.io.File;
import java.nio.file.Files;

public class WakeSampleStoreProbe {
    private static void check(boolean b){if(!b)throw new AssertionError();}
    private static File file(File d,String n)throws Exception{File f=new File(d,n);Files.write(f.toPath(),new byte[]{1,2,3});return f;}
    public static void main(String[] args)throws Exception{
        File dir=new File(args[0]);String a="11111111-1111-4111-8111-111111111111",b="22222222-2222-4222-8222-222222222222",c="33333333-3333-4333-8333-333333333333";
        File aw=file(dir,a+".wav"),aj=file(dir,a+".json"),bw=file(dir,b+".wav"),bj=file(dir,b+".json"),orphan=file(dir,c+".wav"),unrelated=file(dir,"do-not-delete.txt");
        check(!WakeSampleStore.deletePair(dir,"../do-not-delete"));check(unrelated.exists());
        check(WakeSampleStore.deletePair(dir,a));check(!aw.exists()&&!aj.exists());check(bw.exists()&&bj.exists()&&orphan.exists());
        File blocked=new File(dir,c+".json");check(blocked.mkdir());check(!WakeSampleStore.deleteAll(dir));check(blocked.isDirectory()&&unrelated.exists());
        check(!bw.exists()&&!bj.exists()&&!orphan.exists());check(blocked.delete());
        check(WakeSampleStore.deleteAll(dir));check(unrelated.exists());

        File legacy=new File(dir,"wake-training"),study=new File(dir,"wake-study");
        check(legacy.mkdir()&&study.mkdir());
        File owner=file(legacy,a+".wav");file(study,a+".wav");file(study,a+".json");
        check(WakeSampleStore.deleteAll(study)&&owner.exists());
        var session=WakeStudy.session(" Speaker-01 ","test","quiet",200,"reverberant",100);
        check(session.speaker().equals("speaker-01")&&WakeSampleStore.validId(session.id()));
        check(WakeStudy.kind(3).equals("positive")&&WakeStudy.limitSeconds(3)==4);
        check(WakeStudy.kind(6).equals("negative")&&WakeStudy.limitSeconds(6)==120);
        String csv=WakeStudy.row(b,session,3,"accepted",16000);
        check(csv.contains("\"Окей, Уайли\"")&&csv.contains("\"reverberant\",\"\",\"\",\"accepted\""));
        try{WakeStudy.alias("Имя диктора");throw new AssertionError();}catch(IllegalArgumentException expected){}
        try{WakeStudy.row(b,session,3,"accepted",16);throw new AssertionError();}catch(IllegalArgumentException expected){}
    }
}
