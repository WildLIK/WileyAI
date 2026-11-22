package ru.wildlik.wileyai.mobile;

import java.nio.file.*;
import java.util.*;

public class AcousticDiagnosticsProbe {
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        Path dir = Path.of(args[0]);
        short[] word = new short[16000 * 8 + 100];
        for (int i = 0; i < word.length; i++) word[i] = (short)(i * 6427);
        AcousticCapture audio = new AcousticCapture();
        audio.feed(word, word.length);
        AcousticCapture.Window mark = audio.mark(false);
        check(mark.start == 100 && mark.event == word.length && mark.length == 128000);
        AcousticCapture.Window candidate = audio.mark(true);
        short[] tail = new short[50000];
        Arrays.fill(tail, (short)-500);
        check(candidate.add(tail, tail.length));
        check(candidate.length == 176000);
        check(candidate.samples[0] == word[100] && candidate.samples[175999] == -500);
        audio.reset();
        check(audio.mark(false).length == 0 && audio.position() == 0);
        Path raw = dir.resolve("expected.pcm");
        try (var out = Files.newOutputStream(raw)) { AcousticAudio.pcm(out, word, word.length); }
        Path flac = dir.resolve("test.flac");
        AcousticAudio.encode(raw, flac, true);
        short[] copy = AcousticAudio.read(flac, 0, word.length);
        check(Arrays.equals(word, copy));
        check(Arrays.equals(Arrays.copyOfRange(word, 2047, 2222), AcousticAudio.read(flac, 2047, 175)));
        Path wav = dir.resolve("test.wav");
        AcousticAudio.encode(raw, wav, false);
        check(Arrays.equals(word, AcousticAudio.read(wav, 0, word.length)));
        Path preview = dir.resolve("preview.wav");
        AcousticAudio.playbackWav(flac, preview, 2047, 175);
        check(Arrays.equals(Arrays.copyOfRange(word, 2047, 2222), AcousticAudio.read(preview, 0, 175)));
        AcousticAudio.playbackWav(wav, preview, word.length - 3, 10);
        check(Arrays.equals(Arrays.copyOfRange(word, word.length - 3, word.length), AcousticAudio.read(preview, 0, 10)));
    }
}
