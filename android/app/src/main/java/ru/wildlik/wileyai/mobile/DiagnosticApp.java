package ru.wildlik.wileyai.mobile;
import android.app.Application;
public final class DiagnosticApp extends Application {
 @Override public void onCreate(){super.onCreate();WakeSettings.initializeNewInstall(this);DiagnosticLog.initialize(this);}
}
