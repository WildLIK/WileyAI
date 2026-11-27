package ru.wildlik.wileyai.mobile;

import java.util.List;

/** Pinned GigaAM v3 RNN-T (non-punct) ONNX export for sherpa-onnx; sizes and SHA-256 from the Hugging Face LFS manifest. */
final class GigaAmModel {
    static final String ID = "sherpa-onnx-nemo-transducer-giga-am-v3-russian-2025-12-16";
    private static final String REVISION = "0424d62637b37d8b7b1eb0f75a04d78dec55fdcc";
    static final String BASE = "https://huggingface.co/csukuangfj/" + ID + "/resolve/" + REVISION + "/";
    static final String LICENSE = "MIT";
    /** Verified upstream digest of tokens.txt (plain file, not LFS). */
    static final String TOKENS_SHA256 = "17cc514451bcceac9c280068c71502f8448f99e9fb1456b8d0761651fd0392f2";
    /** 64 mel bins, 16 kHz; the vocabulary is 32 lowercase Cyrillic letters only: no digits and no Latin. */
    static final int FEATURE_DIM = 64, SAMPLE_RATE = 16000, THREADS = 2;
    static final long SPACE_BUDGET = 600L * 1024 * 1024;
    private static final long ENCODER_BYTES = 224570814L, DECODER_BYTES = 3331651L, JOINER_BYTES = 1440448L, TOKENS_BYTES = 196L;
    record File(String name, long bytes, String sha256) {}
    static final File ENCODER = new File("encoder.int8.onnx", ENCODER_BYTES,
        "0ec54e5f130a91c0f228d21795ede10b31c992a1f73e45dcd827e843a71a9b50");
    static final File DECODER = new File("decoder.onnx", DECODER_BYTES,
        "5d1cfef155d8e07f213bd2f3229b5f6c5c29355c7fa5c1b9eb62cb1925725254");
    static final File JOINER = new File("joiner.onnx", JOINER_BYTES,
        "fd1d02f45c2ad3d6b67cc149811ad794ab4b020ed49a0a9e2790a8619d1cddd8");
    static final File TOKENS = new File("tokens.txt", TOKENS_BYTES, TOKENS_SHA256);
    static final List<File> FILES = List.of(ENCODER, DECODER, JOINER, TOKENS);
    static long totalBytes() { return ENCODER_BYTES + DECODER_BYTES + JOINER_BYTES + TOKENS_BYTES; }
    static File byName(String name) {
        for (File file : FILES) if (file.name().equals(name)) return file;
        return null;
    }
    static String sizeText() { return String.format(java.util.Locale.ROOT, "%.1f", totalBytes() / 1048576.0); }
    private GigaAmModel() {}
}
