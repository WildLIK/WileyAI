package ru.wildlik.wileyai.mobile;

import java.io.File;

/** Deletes only UUID-named sample files inside the caller-supplied private directory. */
final class WakeSampleStore {
    private static final String ID="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
    static boolean validId(String id){return id!=null&&id.matches(ID);}
    static boolean deletePair(File directory,String id) {
        if(directory==null || id==null || !id.matches(ID)) return false;
        File wav=new File(directory,id+".wav"),meta=new File(directory,id+".json");
        if(!deleteFile(wav)) return false;
        return deleteFile(meta);
    }
    static boolean deleteAll(File directory) {
        if(directory==null) return false;
        if(!directory.exists()) return true;
        File[] files=directory.listFiles((folder,name)->name.matches(ID+"\\.(wav|json)"));
        if(files==null) return false;
        boolean success=true;
        for(File file:files) if(!deleteFile(file)) success=false;
        return success;
    }
    private static boolean deleteFile(File file) {
        if(!file.exists()) return true;
        return file.isFile() && file.delete();
    }
    private WakeSampleStore() {}
}
