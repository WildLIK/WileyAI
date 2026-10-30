package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

public final class AssistantSettingsActivity extends Activity {
    @Override public void onCreate(Bundle saved) { super.onCreate(saved); startActivity(new Intent(this, MainActivity.class).setAction(HandsFreeService.SETTINGS).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)); finish(); }
}
