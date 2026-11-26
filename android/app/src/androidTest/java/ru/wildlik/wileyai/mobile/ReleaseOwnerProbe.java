package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Build;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.util.List;

/** Verifies the actual release assets and CAM++ runtime using repository synthetic audio only. */
final class ReleaseOwnerProbe {
    static String run(Context target, Context test) throws Exception {
        if ((!"ranchu".equals(Build.HARDWARE) && !"goldfish".equals(Build.HARDWARE))
                || BuildConfig.DEBUG || OwnerSpeakerFilter.hasEnrolledProfile(target)) {
            throw new IOException("The probe requires an isolated release emulator with no owner profile");
        }
        var model = WakeModelAssets.ensureCamPlus(target);
        Files.write(model, new byte[]{0});
        WakeModelAssets.ensureCamPlus(target);
        if (Files.size(model) != 28_281_165 || WakeModelAssets.hasLiveKit(target)) throw new IOException("Wrong release model contents");
        byte[] wav;
        try (var in = test.getAssets().open("wake_b5_time.wav")) { wav = in.readAllBytes(); }
        short[] clip = new short[(wav.length - 44) / 2];
        ByteBuffer.wrap(wav, 44, wav.length - 44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(clip);
        try (var owner = OwnerSpeakerFilter.open(model, 1)) {
            if (owner.enroll(target, List.of(clip, clip, clip)) != 3) throw new IOException("Enrollment did not use 3 clips");
            var check = owner.verifyAgainstReference(OwnerSpeakerFilter.loadProfile(target), clip, clip.length, 0.38f);
            if (!check.accepted() || !OwnerSpeakerFilter.hasEnrolledProfile(target)) throw new IOException("Stored profile did not verify");
        }
        return "CAM++ verified, damaged cache repaired, synthetic profile saved and reloaded";
    }

    private ReleaseOwnerProbe() {}
}
