package ru.wildlik.wileyai.mobile;

/** Upstream URL/size/MD5; SHA-256 is the published LFS digest of the pinned mirror. */
final class RussianSpeechModel {
    static final String ID = "vosk-model-small-ru-0.22";
    static final String URL = "https://alphacephei.com/vosk/models/" + ID + ".zip";
    static final String METADATA = "https://alphacephei.com/vosk/models/model-list.json";
    static final String SHA_SOURCE = "https://huggingface.co/localstack/vosk-models/blob/a0cabdd6801bd201c783afcc096208cde59fa182/vosk-model-small-ru-0.22.zip";
    static final String MIRROR = "https://huggingface.co/localstack/vosk-models/resolve/a0cabdd6801bd201c783afcc096208cde59fa182/vosk-model-small-ru-0.22.zip?download=true";
    static final long SPACE_BUDGET = 400L * 1024 * 1024;
    static final VerifiedModelInstaller.Spec SPEC = new VerifiedModelInstaller.Spec(ID, 46236750,
        "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4", "d1759dc83eb8fd87850129afbd9f4b7b", 200L * 1024 * 1024);
}
