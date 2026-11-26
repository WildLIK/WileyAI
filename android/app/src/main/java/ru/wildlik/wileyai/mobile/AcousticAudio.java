package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.nio.file.*;

/** Diagnostic PCM16 mono encoder. FLAC uses fixed blocks and verbatim subframes per RFC 9639. */
final class AcousticAudio {
    private static final int BLOCK = 2048, RATE = AcousticCapture.RATE, COMPARISON_SECONDS = 3602;
    private static final int[] CRC8 = crcTable(8, 0x07), CRC16 = crcTable(16, 0x8005);

    private static int[] crcTable(int bits, int polynomial) {
        int[] table = new int[256];
        for (int i = 0; i < table.length; i++) {
            int v = i << (bits - 8);
            for (int j = 0; j < 8; j++) v = (v << 1) ^ ((v & (1 << (bits - 1))) != 0 ? polynomial : 0);
            table[i] = v & ((1 << bits) - 1);
        }
        return table;
    }

    static void pcm(OutputStream out, short[] samples, int count) throws IOException {
        byte[] bytes = new byte[2 * Math.min(BLOCK, count)];
        for (int pos = 0; pos < count;) {
            int n = Math.min(count - pos, BLOCK);
            for (int i = 0; i < n; i++) {
                short s = samples[pos + i];
                bytes[2 * i] = (byte)s;
                bytes[2 * i + 1] = (byte)(s >>> 8);
            }
            out.write(bytes, 0, n * 2);
            pos += n;
        }
    }

    static void encode(Path raw, Path result, boolean flac) throws IOException {
        encode(raw, result, flac, 600);
    }

    static void encodeComparisonFlac(Path raw, Path result) throws IOException {
        encode(raw, result, true, COMPARISON_SECONDS);
    }

    private static void encode(Path raw, Path result, boolean flac, int seconds) throws IOException {
        long bytes = Files.size(raw), count = bytes / 2;
        if (bytes % 2 != 0 || count > (long) RATE * seconds) throw new IOException("invalid PCM length");
        try (DataOutputStream out = new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(result)));
             InputStream in = new BufferedInputStream(Files.newInputStream(raw))) {
            if (!flac) {
                wavHeader(out, (int)bytes);
                byte[] buffer = new byte[8192];
                for (int n; (n = in.read(buffer)) != -1;) out.write(buffer, 0, n);
                return;
            }
            out.writeBytes("fLaC"); out.writeInt(0x80000022);
            out.writeShort(BLOCK); out.writeShort(BLOCK);
            out.write(new byte[6]); // Frame size bounds unknown.
            out.writeLong(((long)RATE << 44) | (15L << 36) | count);
            out.write(new byte[16]); // STREAMINFO MD5 optional. Export records SHA-256.
            byte[] block = new byte[BLOCK * 2];
            for (int number = 0, n; (n = readBlock(in, block)) != 0; number++) {
                ByteArrayOutputStream header = new ByteArrayOutputStream(10);
                header.write(0xff); header.write(0xf8); header.write(0x75); header.write(0x08);
                codedNumber(header, number);
                header.write((n / 2 - 1) >>> 8); header.write((n / 2 - 1) & 255);
                int check = 0, crc = 0;
                for (byte b : header.toByteArray()) {
                    check = CRC8[check ^ (b & 255)];
                    crc = update16(crc, b);
                }
                header.writeTo(out); out.writeByte(check); out.writeByte(2); // Verbatim, no wasted bits.
                crc = update16(update16(crc, check), 2);
                for (int i = 0; i < n; i += 2) {
                    byte lo = block[i], hi = block[i + 1];
                    block[i] = hi;
                    block[i + 1] = lo;
                    crc = update16(update16(crc, hi), lo);
                }
                out.write(block, 0, n);
                out.writeShort(crc);
            }
        }
    }

    private static int readBlock(InputStream in, byte[] block) throws IOException {
        int size = 0;
        while (size < block.length) {
            int n = in.read(block, size, block.length - size);
            if (n == -1) break;
            size += n;
        }
        return size;
    }

    private static int update16(int crc, int b) { return ((crc << 8) ^ CRC16[(crc >>> 8) ^ (b & 255)]) & 65535; }
    private static void little(DataOutputStream file, int value) throws IOException { file.writeInt(Integer.reverseBytes(value)); }
    private static void wavHeader(DataOutputStream out, int bytes) throws IOException {
        out.writeBytes("RIFF"); little(out, bytes + 36); out.writeBytes("WAVEfmt ");
        little(out, 16); little(out, 0x00010001); little(out, RATE); little(out, RATE * 2);
        little(out, 0x00100002); out.writeBytes("data"); little(out, bytes);
    }
    private static void codedNumber(ByteArrayOutputStream dest, int n) {
        if (n < 128) dest.write(n);
        else if (n < 2048) { dest.write(0xc0 | (n >>> 6)); dest.write(0x80 | (n & 63)); }
        else { dest.write(0xe0 | (n >>> 12)); dest.write(0x80 | ((n >>> 6) & 63)); dest.write(0x80 | (n & 63)); }
    }

    /** Read a bounded excerpt of an app-owned file without allocating the whole continuous record. */
    static short[] read(Path path, long start, int count) throws IOException {
        if (start < 0 || count < 0 || count > 11 * RATE) throw new IOException("invalid range");
        ByteArrayOutputStream pcm = new ByteArrayOutputStream(count * 2);
        try (RandomAccessFile in = new RandomAccessFile(path.toFile(), "r")) {
            int kind = in.readInt();
            transfer(in, kind, start, range(in, kind, start, count), pcm);
        }
        byte[] bytes = pcm.toByteArray();
        short[] result = new short[bytes.length / 2];
        java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(result);
        return result;
    }

    /** The phone's vendor FLAC decoder may reject valid verbatim frames. Stream an exact WAV for local playback. */
    static void playbackWav(Path path, Path result, long start, int requested) throws IOException {
        try (RandomAccessFile in = new RandomAccessFile(path.toFile(), "r");
             DataOutputStream out = new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(result)))) {
            int kind = in.readInt();
            int count = range(in, kind, start, requested);
            if (count == 0) throw new IOException("no PCM");
            wavHeader(out, count * 2);
            transfer(in, kind, start, count, out);
        }
    }

    private static int range(RandomAccessFile in, int kind, long start, int requested) throws IOException {
        long total;
        if (kind == 0x52494646) total = (in.length() - 44) / 2;
        else if (kind == 0x664c6143) { in.seek(18); total = in.readLong() & ((1L << 36) - 1); }
        else throw new IOException("unsupported format");
        int maxSeconds = kind == 0x664c6143 ? COMPARISON_SECONDS : 600;
        if (total < 0 || total > (long) RATE * maxSeconds || start < 0 || requested < 0) throw new IOException("invalid range");
        return (int)Math.min(requested, Math.max(0, total - start));
    }

    private static void transfer(RandomAccessFile in, int kind, long start, int count, OutputStream out) throws IOException {
        if (count == 0) return;
        byte[] pcm = new byte[BLOCK * 2];
        if (kind == 0x52494646) {
            in.seek(44 + start * 2);
            for (int done = 0; done < count;) {
                int n = Math.min(count - done, BLOCK);
                in.readFully(pcm, 0, n * 2);
                out.write(pcm, 0, n * 2);
                done += n;
            }
            return;
        }
        in.seek(42);
        for (long at = 0; count > 0;) {
            if (in.readInt() != 0xfff87508) throw new IOException("unexpected FLAC frame");
            int number = in.readUnsignedByte();
            if (number >= 128) in.skipBytes(number >= 224 ? 2 : 1);
            int n = in.readUnsignedShort() + 1;
            in.readUnsignedByte();
            if (in.readUnsignedByte() != 2 || n > BLOCK) throw new IOException("unexpected subframe");
            long next = in.getFilePointer() + n * 2L + 2;
            if (next > in.length()) throw new EOFException();
            if (at + n > start) {
                int skip = (int)Math.max(0, start - at);
                int len = Math.min(n - skip, count) * 2;
                in.skipBytes(skip * 2);
                in.readFully(pcm, 0, len);
                for (int i = 0; i < len; i += 2) {
                    byte hi = pcm[i]; pcm[i] = pcm[i + 1]; pcm[i + 1] = hi;
                }
                out.write(pcm, 0, len);
                count -= len / 2;
            }
            at += n;
            in.seek(next);
        }
    }
    private AcousticAudio() {}
}
