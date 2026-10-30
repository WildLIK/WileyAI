package ru.wildlik.wileyai.mobile;

import android.os.Bundle;
import android.service.voice.*;

public final class WileySessionService extends VoiceInteractionSessionService {
    @Override public VoiceInteractionSession onNewSession(Bundle args) { return new WileyVoiceSession(this); }
}
