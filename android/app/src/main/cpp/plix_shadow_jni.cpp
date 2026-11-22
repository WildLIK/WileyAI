#include <jni.h>
#include "plix_observer.hpp"

namespace {
using namespace wiley_plix;
struct Engine {
    std::ifstream filters, bank;
    Frontend frontend;
    Head head;
    std::array<int16_t, Rate> pcm{};
    std::array<float, Mels * Frames> features{};
    std::array<float, Embedding> embedding{};
    Runtime runtime;
    explicit Engine(const std::string& dir)
        : filters(dir + "/filters.bin", std::ios::binary), bank(dir + "/head.bin", std::ios::binary),
          frontend(filters), head(bank) {
        runtime.load((dir + "/multi.onnx").c_str(), features);
    }
};
}

extern "C" JNIEXPORT jlong JNICALL
Java_ru_wildlik_wileyai_mobile_H2Shadow_open(JNIEnv* env, jclass, jstring path) {
    const char* raw = env->GetStringUTFChars(path, nullptr);
    if (!raw) return 0;
    auto release = [env,path](const char* chars){ env->ReleaseStringUTFChars(path, chars); };
    std::unique_ptr<const char, decltype(release)> guard(raw, release);
    try {
        return reinterpret_cast<jlong>(new Engine(raw));
    } catch (const std::exception&) { return 0; }
}

extern "C" JNIEXPORT jfloat JNICALL
Java_ru_wildlik_wileyai_mobile_H2Shadow_score(JNIEnv* env, jclass, jlong handle, jshortArray input) {
    auto* engine = reinterpret_cast<Engine*>(handle);
    if (!engine || env->GetArrayLength(input) != 16000) return NAN;
    env->GetShortArrayRegion(input, 0, 16000, engine->pcm.data());
    if (env->ExceptionCheck()) return NAN;
    try {
        engine->frontend.calculate(engine->pcm, engine->features, true);
        std::fill(engine->pcm.begin(), engine->pcm.end(), 0);
        engine->runtime.infer(engine->embedding);
        return engine->head.score(engine->embedding);
    } catch (const std::exception&) { return NAN; }
}

extern "C" JNIEXPORT void JNICALL
Java_ru_wildlik_wileyai_mobile_H2Shadow_close(JNIEnv*, jclass, jlong handle) {
    delete reinterpret_cast<Engine*>(handle);
}
