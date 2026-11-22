package ru.wildlik.wileyai.mobile;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Exposes only the explicitly prepared log, read-only, via Android's temporary URI grant. */
public final class DiagnosticShareProvider extends ContentProvider {
    @Override public boolean onCreate(){return true;}
    private File file(Uri uri) throws FileNotFoundException {
        if (!"/log.txt".equals(uri.getPath()) || getContext()==null) throw new FileNotFoundException();
        return new File(getContext().getCacheDir(),"wileyai-diagnostic-share.txt");
    }
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException();
        return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public String getType(Uri uri){return "text/plain";}
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){
        String[] cols=projection==null?new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE}:projection;
        MatrixCursor result=new MatrixCursor(cols);Object[] row=new Object[cols.length];
        try{File f=file(uri);for(int i=0;i<cols.length;i++){if(OpenableColumns.DISPLAY_NAME.equals(cols[i]))row[i]="WileyAI_Log.txt";else if(OpenableColumns.SIZE.equals(cols[i]))row[i]=f.length();}result.addRow(row);}catch(FileNotFoundException ignored){}
        return result;
    }
    @Override public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
    @Override public int update(Uri uri,ContentValues values,String selection,String[] args){throw new UnsupportedOperationException();}
    @Override public int delete(Uri uri,String selection,String[] args){throw new UnsupportedOperationException();}
}
