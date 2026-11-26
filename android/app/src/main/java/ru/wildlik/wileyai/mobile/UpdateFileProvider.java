package ru.wildlik.wileyai.mobile;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.FileNotFoundException;

/** Only the verified, app-private APK can be opened using a temporary read grant. */
public final class UpdateFileProvider extends ContentProvider {
    static final String MIME = "application/vnd.android.package-archive";
    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) { return MIME; }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"/WileyAI-Update.apk".equals(uri.getPath()) || !"r".equals(mode) || getContext() == null) {
            throw new FileNotFoundException();
        }
        return ParcelFileDescriptor.open(ReleaseUpdates.file(getContext()), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        if (!"/WileyAI-Update.apk".equals(uri.getPath()) || getContext() == null) return null;
        String[] cols = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
        MatrixCursor cursor = new MatrixCursor(cols);
        Object[] row = new Object[cols.length];
        for (int i = 0; i < cols.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) row[i] = "WileyAI-Update.apk";
            if (OpenableColumns.SIZE.equals(cols[i])) row[i] = ReleaseUpdates.file(getContext()).length();
        }
        cursor.addRow(row);
        return cursor;
    }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
