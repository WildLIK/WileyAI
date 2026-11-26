package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Debug;
import android.os.SystemClock;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Hardware S23+ verification probe for Stage 1 improvements:
 * 1. LiveKit C v2 (C_v2.onnx) via native libwiley_livekit_compare.so (latency, determinism, scores).
 * 2. Experimental CAM++ 3D-Speaker OwnerSpeakerFilter (explicit enrollment, pre-roll reuse, owner vs TTS vs stranger, toggle off).
 * 3. Fused-command prefix cleaning in WakePhrase.firstCommand(..., confirmedNameHandoff=true).
 */
final class WakeStage1Probe {
    static String run(Context context) throws Exception {
        Path dir = context.getCacheDir().toPath().resolve("wake-stage1-s23");
        Path cV2Model = dir.resolve("C_v2.onnx");
        Path camModel = dir.resolve("campplus.onnx");
        if (!Files.isRegularFile(cV2Model) || !Files.isRegularFile(camModel)) {
            throw new AssertionError("Missing staged models in " + dir);
        }

        JSONObject report = new JSONObject();
        report.put("pss_before_kb", pssKb());

        // 1. LiveKit C v2 native ARM64 benchmark + determinism check
        System.loadLibrary("wiley_livekit_compare");
        long tOpen0 = SystemClock.elapsedRealtimeNanos();
        long handle = WakeComparison.open(cV2Model.toAbsolutePath().toString());
        long cV2OpenMs = (SystemClock.elapsedRealtimeNanos() - tOpen0) / 1_000_000L;
        if (handle == 0) throw new AssertionError("Could not open C_v2.onnx");

        JSONArray lkResults = new JSONArray();
        List<Long> blockUs = new ArrayList<>();
        try {
            String[] clips = {"owner_pos_1.pcm", "owner_pos_2.pcm", "owner_pos_3.pcm", "tts_pos_1.pcm", "stranger_neg_1.pcm"};
            for (String name : clips) {
                Path p = dir.resolve(name);
                if (!Files.isRegularFile(p)) continue;
                short[] pcm = readPcm(p);
                if (!WakeComparison.reset(handle)) throw new AssertionError("Reset failed");
                int blocks = pcm.length / 1280;
                short[] chunk = new short[1280];
                float maxScore = 0f;
                int streak = 0;
                int hitBlock = -1;
                for (int b = 0; b < blocks; b++) {
                    System.arraycopy(pcm, b * 1280, chunk, 0, 1280);
                    long t0 = SystemClock.elapsedRealtimeNanos();
                    float s = WakeComparison.score(handle, chunk);
                    blockUs.add((SystemClock.elapsedRealtimeNanos() - t0) / 1000L);
                    if (!Float.isFinite(s)) throw new AssertionError("Non-finite score");
                    if (s > maxScore) maxScore = s;
                    if (s >= 0.99f) {
                        streak++;
                        if (streak >= 2 && hitBlock < 0) hitBlock = b;
                    } else {
                        streak = 0;
                    }
                }
                JSONObject item = new JSONObject();
                item.put("clip", name);
                item.put("blocks", blocks);
                item.put("max_score", maxScore);
                item.put("hit_99x2", hitBlock >= 0);
                item.put("hit_block", hitBlock);
                lkResults.put(item);
            }
            // Determinism check on owner_pos_1.pcm
            short[] detPcm = readPcm(dir.resolve("owner_pos_1.pcm"));
            float[] run1 = scoreAll(handle, detPcm);
            float[] run2 = scoreAll(handle, detPcm);
            if (!Arrays.equals(run1, run2)) throw new AssertionError("C_v2.onnx reset determinism failed");
        } finally {
            WakeComparison.close(handle);
        }

        long[] sortedUs = blockUs.stream().mapToLong(Long::longValue).sorted().toArray();
        long p50Us = sortedUs[sortedUs.length / 2];
        long p95Us = sortedUs[(int) Math.min(sortedUs.length - 1, Math.floor(sortedUs.length * 0.95))];
        double meanUs = Arrays.stream(sortedUs).average().orElse(0.0);
        // 1 second of audio = 12.5 blocks (80 ms/block)
        double cpuMsPerSec = (meanUs * 12.5) / 1000.0;

        JSONObject lkObj = new JSONObject();
        lkObj.put("open_ms", cV2OpenMs);
        lkObj.put("blocks_measured", sortedUs.length);
        lkObj.put("block_p50_us", p50Us);
        lkObj.put("block_p95_us", p95Us);
        lkObj.put("cpu_ms_per_sec", Math.round(cpuMsPerSec * 100.0) / 100.0);
        lkObj.put("determinism_ok", true);
        lkObj.put("clips", lkResults);
        report.put("livekit_c_v2", lkObj);
        report.put("pss_after_livekit_kb", pssKb());

        // 2. CAM++ 3D-Speaker OwnerSpeakerFilter ARM64 benchmark + enrollment + verification
        OwnerSpeakerFilter.clearEnrollment(context);
        long tCam0 = SystemClock.elapsedRealtimeNanos();
        JSONObject camObj = new JSONObject();
        try (OwnerSpeakerFilter filter = OwnerSpeakerFilter.open(camModel, 1)) {
            long camOpenMs = (SystemClock.elapsedRealtimeNanos() - tCam0) / 1_000_000L;
            camObj.put("open_ms", camOpenMs);
            camObj.put("dim", filter.embeddingDim());
            report.put("pss_with_campplus_kb", pssKb());

            // Explicit enrollment from 3 enrollment owner clips
            List<short[]> enrollClips = new ArrayList<>();
            for (int i = 1; i <= 3; i++) {
                Path ep = dir.resolve("enroll_" + i + ".pcm");
                if (Files.isRegularFile(ep)) enrollClips.add(readPcm(ep));
            }
            int enrolledCount = filter.enroll(context, enrollClips);
            camObj.put("enrolled_clips", enrolledCount);
            byte[] profileBefore = Files.readAllBytes(OwnerSpeakerFilter.profilePath(context));

            // Test disabled toggle (must bypass without rejecting)
            OwnerSpeakerFilter.setEnabled(context, false);
            OwnerSpeakerFilter.Result disabledRes = filter.verify(context, readPcm(dir.resolve("stranger_neg_1.pcm")), 24000);
            if (!disabledRes.accepted() || !"filter_disabled".equals(disabledRes.reason())) {
                throw new AssertionError("Disabled filter did not bypass cleanly");
            }
            camObj.put("disabled_bypass_ok", true);

            // Enable with calibrated threshold 0.38
            OwnerSpeakerFilter.setEnabled(context, true);
            OwnerSpeakerFilter.setThreshold(context, 0.38f);

            String[] testClips = {"owner_pos_1.pcm", "owner_pos_2.pcm", "owner_pos_3.pcm", "tts_pos_1.pcm", "stranger_neg_1.pcm"};
            JSONArray camResults = new JSONArray();
            List<Long> camUs = new ArrayList<>();
            for (String name : testClips) {
                Path p = dir.resolve(name);
                if (!Files.isRegularFile(p)) continue;
                short[] full = readPcm(p);
                // Simulate 1.5s pre-roll buffer reuse (max 24,000 samples, zero extra recording)
                int len = Math.min(full.length, 24000);
                OwnerSpeakerFilter.Result r = filter.verify(context, full, len);
                camUs.add(r.elapsedUs());
                JSONObject item = new JSONObject();
                item.put("clip", name);
                item.put("accepted", r.accepted());
                item.put("similarity", Math.round(r.similarity() * 10000.0) / 10000.0);
                item.put("threshold", r.threshold());
                item.put("elapsed_ms", Math.round(r.elapsedUs() / 10.0) / 100.0);
                item.put("reason", r.reason());
                camResults.put(item);
            }
            // Verify profile was NOT mutated by live verifications (strictly zero auto-learning!)
            byte[] profileAfter = Files.readAllBytes(OwnerSpeakerFilter.profilePath(context));
            if (!Arrays.equals(profileBefore, profileAfter)) {
                throw new AssertionError("Profile mutated during verify!");
            }
            camObj.put("zero_autolearn_ok", true);
            long[] sortedCam = camUs.stream().mapToLong(Long::longValue).sorted().toArray();
            camObj.put("verify_p50_ms", Math.round(sortedCam[sortedCam.length / 2] / 10.0) / 100.0);
            camObj.put("verify_p95_ms", Math.round(sortedCam[(int) Math.min(sortedCam.length - 1, Math.floor(sortedCam.length * 0.95))] / 10.0) / 100.0);
            camObj.put("clips", camResults);

            // Clean up experimental toggle back to off by default
            OwnerSpeakerFilter.setEnabled(context, false);
            OwnerSpeakerFilter.clearEnrollment(context);
        }
        report.put("campplus", camObj);
        report.put("pss_after_close_kb", pssKb());

        // 3. Fused-command prefix fix verification on device
        java.util.function.Predicate<String> safeCmd = candidate -> {
            PhoneCommands.Action a = PhoneCommands.parse(candidate, true);
            return a != null && !a.kind.equals("open") && !a.kind.equals("media_search") && !a.kind.equals("media_play_search");
        };
        if (!"включи музыку".equals(WakePhrase.firstCommand("уали включи музыку", WakePhrase.SHORT, safeCmd, true))) {
            throw new AssertionError("Fused music prefix fix failed");
        }
        if (!"сколько времени".equals(WakePhrase.firstCommand("вале, сколько времени", WakePhrase.SHORT, safeCmd, true))) {
            throw new AssertionError("Fused time prefix fix failed");
        }
        if (!"вале открой браузер".equals(WakePhrase.firstCommand("вале открой браузер", WakePhrase.SHORT, safeCmd, true))) {
            throw new AssertionError("Fused open guard failed");
        }
        report.put("fused_prefix_fix_ok", true);

        Files.write(dir.resolve("stage1-s23-report.json"), report.toString(2).getBytes(StandardCharsets.UTF_8));
        return report.toString();
    }

    static String runE2e(Context context) throws Exception {
        JSONObject out = new JSONObject();

        // 1. Bundled asset extraction & SHA-256 verification
        Path cV2 = WakeModelAssets.ensureLiveKitV2(context);
        Path cam = WakeModelAssets.ensureCamPlus(context);
        if (!Files.isRegularFile(cV2) || !Files.isRegularFile(cam)) {
            throw new AssertionError("Bundled Stage 1 models not extracted");
        }
        out.put("assets_verified", true);

        // 2. WakeSettings & AudioRouteManager independent rollback toggles
        int origEngine = WakeSettings.wakeEngine(context);
        boolean origAec = AudioRouteManager.isAecEnabled(context);
        boolean origNs = AudioRouteManager.isNsEnabled(context);
        boolean origBt = AudioRouteManager.isBtScoEnabled(context);
        try {
            WakeSettings.setWakeEngine(context, WakeSettings.ENGINE_LIVEKIT_V2_CAM);
            if (WakeSettings.wakeEngine(context) != WakeSettings.ENGINE_LIVEKIT_V2_CAM || !OwnerSpeakerFilter.isEnabled(context)) {
                throw new AssertionError("ENGINE_LIVEKIT_V2_CAM toggle failed");
            }
            WakeSettings.setWakeEngine(context, WakeSettings.ENGINE_VOSK);
            if (WakeSettings.wakeEngine(context) != WakeSettings.ENGINE_VOSK || OwnerSpeakerFilter.isEnabled(context)) {
                throw new AssertionError("ENGINE_VOSK fallback toggle failed");
            }
            AudioRouteManager.setAecEnabled(context, false);
            if (AudioRouteManager.isAecEnabled(context)) throw new AssertionError("AEC rollback toggle failed");
            AudioRouteManager.setNsEnabled(context, false);
            if (AudioRouteManager.isNsEnabled(context)) throw new AssertionError("NS rollback toggle failed");
            AudioRouteManager.setBtScoEnabled(context, false);
            if (AudioRouteManager.isBtScoEnabled(context)) throw new AssertionError("BT SCO rollback toggle failed");
            out.put("route_summary", AudioRouteManager.routeSummary(context));
            out.put("others_need_mic", AudioRouteManager.othersNeedMic(context));
        } finally {
            WakeSettings.setWakeEngine(context, origEngine);
            AudioRouteManager.setAecEnabled(context, origAec);
            AudioRouteManager.setNsEnabled(context, origNs);
            AudioRouteManager.setBtScoEnabled(context, origBt);
        }

        // 3. WakeActivationJournal: pre/post WAV, missed command, false alarm mark, ZIP export, clear
        WakeActivationJournal.clearAll(context);
        short[] dummy = new short[16000];
        for (int i = 0; i < dummy.length; i++) dummy[i] = (short) (i % 500);
        String evId = WakeActivationJournal.recordEventAsync(
                context, "livekit_c_v2_cam", 0.992, 0.621, 0.38, 0.98,
                "VOICE_RECOGNITION/BUILTIN_MIC", false, 52L, 74L,
                "accepted", "accepted", dummy);
        Thread.sleep(350);
        WakeActivationJournal.savePostAudioAsync(context, evId, dummy, dummy.length);
        WakeActivationJournal.updateAsrTextAsync(context, evId, "вайли включи музыку");
        WakeActivationJournal.recordMissedCommandAsync(context, dummy, dummy.length, "user_missed_command");
        Thread.sleep(450);

        List<WakeActivationJournal.Entry> entries = WakeActivationJournal.listEvents(context);
        if (entries.size() != 2) throw new AssertionError("Expected 2 journal entries, got " + entries.size());
        String faMsg = WakeActivationJournal.markLastFalseAlarm(context);
        if (!faMsg.contains("отмечена")) throw new AssertionError("Unexpected FA mark msg: " + faMsg);

        Path zip = context.getCacheDir().toPath().resolve("e2e-journal-test.zip");
        Files.deleteIfExists(zip);
        WakeActivationJournal.exportZip(context, zip);
        if (!Files.isRegularFile(zip) || Files.size(zip) < 1000) throw new AssertionError("Journal ZIP export failed");
        Files.deleteIfExists(zip);
        if (!WakeActivationJournal.clearAll(context) || !WakeActivationJournal.listEvents(context).isEmpty()) {
            throw new AssertionError("Journal clearAll failed");
        }
        out.put("journal_zip_ok", true);

        // 4. End-to-end LiveKit C v2 + CAM++ -> PcmHandoff -> GigaAM -> WakePhrase -> PhoneCommands
        Path dir = context.getCacheDir().toPath().resolve("wake-stage1-s23");
        if (Files.isRegularFile(dir.resolve("owner_pos_3.pcm")) && GigaAmModelManager.activeModel(context) != null) {
            short[] ownerCmd = readPcm(dir.resolve("owner_pos_3.pcm")); // "Вайли, сколько времени"
            System.loadLibrary("wiley_livekit_compare");
            long h = WakeComparison.open(cV2.toAbsolutePath().toString());
            try (OwnerSpeakerFilter camFilter = OwnerSpeakerFilter.open(cam, 1)) {
                List<short[]> enroll = List.of(
                        readPcm(dir.resolve("enroll_1.pcm")),
                        readPcm(dir.resolve("enroll_2.pcm")),
                        readPcm(dir.resolve("enroll_3.pcm")));
                camFilter.enroll(context, enroll);
                OwnerSpeakerFilter.setEnabled(context, true);

                int blocks = ownerCmd.length / 1280;
                short[] blk = new short[1280];
                int hitSample = -1;
                for (int b = 0; b < blocks; b++) {
                    System.arraycopy(ownerCmd, b * 1280, blk, 0, 1280);
                    if (WakeComparison.score(h, blk) >= 0.98f) {
                        hitSample = (b + 1) * 1280;
                        break;
                    }
                }
                if (hitSample < 0) throw new AssertionError("C_v2 did not trigger on owner_pos_3");
                short[] pre = Arrays.copyOfRange(ownerCmd, Math.max(0, hitSample - 24000), hitSample);
                OwnerSpeakerFilter.Result camRes = camFilter.verify(context, pre, pre.length);
                if (!camRes.accepted()) throw new AssertionError("CAM++ rejected owner_pos_3: " + camRes.similarity());

                long boundary = Math.max(0, hitSample - 1280L * 8L);
                PcmHandoff handoff = new PcmHandoff(ownerCmd.length + 1, ownerCmd.length + 1);
                handoff.append(ownerCmd, hitSample);
                handoff.activate(boundary);
                handoff.append(Arrays.copyOfRange(ownerCmd, hitSample, ownerCmd.length), ownerCmd.length - hitSample);

                GigaAmSpeechEngine giga = new GigaAmSpeechEngine(context, GigaAmRuntime.get(context));
                java.util.concurrent.CountDownLatch latch = new java.util.concurrent.CountDownLatch(1);
                java.util.concurrent.atomic.AtomicReference<String> asr = new java.util.concurrent.atomic.AtomicReference<>("");
                giga.startFromPcm(15000, new OfflineSpeechEngine.Listener() {
                    public void state(String s) {}
                    public void partial(String s) {}
                    public void result(String s) { asr.set(s); }
                    public void error(String s) {}
                    public void finished() { latch.countDown(); }
                }, handoff);
                handoff.seal();
                latch.await(25, java.util.concurrent.TimeUnit.SECONDS);
                giga.close();
                String cleaned = WakePhrase.firstCommand(asr.get(), WakePhrase.SHORT, c -> PhoneCommands.parse(c, true) != null, true);
                PhoneCommands.Action act = PhoneCommands.parse(cleaned, true);
                if (act == null) throw new AssertionError("E2E command unrouted: raw=" + asr.get() + " cleaned=" + cleaned);
                out.put("e2e_asr_raw", asr.get());
                out.put("e2e_command_cleaned", cleaned);
                out.put("e2e_action", act.kind + ":" + act.value);
            } finally {
                WakeComparison.close(h);
                OwnerSpeakerFilter.setEnabled(context, false);
                OwnerSpeakerFilter.clearEnrollment(context);
            }
        }
        return out.toString();
    }

    private static float[] scoreAll(long handle, short[] pcm) {
        if (!WakeComparison.reset(handle)) throw new AssertionError("Reset failed");
        int blocks = pcm.length / 1280;
        float[] out = new float[blocks];
        short[] chunk = new short[1280];
        for (int b = 0; b < blocks; b++) {
            System.arraycopy(pcm, b * 1280, chunk, 0, 1280);
            out[b] = WakeComparison.score(handle, chunk);
        }
        return out;
    }

    private static short[] readPcm(Path file) throws Exception {
        byte[] raw = Files.readAllBytes(file);
        short[] out = new short[raw.length / 2];
        ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(out);
        return out;
    }

    private static int pssKb() {
        Debug.MemoryInfo mi = new Debug.MemoryInfo();
        Debug.getMemoryInfo(mi);
        return mi.getTotalPss();
    }
}
