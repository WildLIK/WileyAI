#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <complex>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <dlfcn.h>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <thread>
#include <vector>

#include "onnxruntime_c_api.h"

namespace wiley_plix {
constexpr size_t Rate = 16000, Fft = 1024, Bins = Fft / 2 + 1;
constexpr size_t Frames = 101, Mels = 64, Embedding = 1280;
constexpr double Pi = 3.14159265358979323846;
template<class T, size_t N>
void read(std::istream& stream, std::array<T, N>& data) {
    if (!stream.read(reinterpret_cast<char*>(data.data()), N * sizeof(T))) {
        throw std::runtime_error("Invalid PCM fixture");
    }
}

struct Clip {
    std::array<int16_t, Rate> pcm{};
    std::array<float, Mels * Frames> mel{};
    std::array<float, Embedding> embedding{};
};

class Frontend {
public:
    explicit Frontend(std::istream& stream) {
        read(stream, window_);
        read(stream, filters_);
        for (size_t i = 0; i < Fft / 2; ++i) roots_[i] = std::polar(1.0, -2 * Pi * i / Fft);
        for (size_t i = 0; i < Fft; ++i) {
            size_t reversed = 0;
            for (size_t source = i, bits = Fft; bits > 1; bits >>= 1, source >>= 1) {
                reversed = (reversed << 1) | (source & 1);
            }
            order_[i] = reversed;
        }
    }

    void calculate(const std::array<int16_t, Rate>& pcm, std::array<float, Mels * Frames>& mel, bool floor = false) {
        if (floor && powers_.empty()) powers_.resize(Frames * Bins);
        std::array<std::complex<double>, Fft> buffer{};
        for (size_t frame = 0; frame < Frames; ++frame) {
            for (size_t i = 0; i < Fft; ++i) {
                int index = int(frame * 160 + i) - int(Fft / 2);
                if (index < 0) index = -index;
                if (index >= int(Rate)) index = 2 * int(Rate - 1) - index;
                buffer[order_[i]] = (pcm[index] / 32768.0) * window_[i];
            }
            for (size_t span = 2; span <= Fft; span *= 2) {
                const size_t half = span / 2;
                for (size_t row = 0; row < Fft; row += span) {
                    for (size_t column = 0; column < half; ++column) {
                        const auto v = buffer[row + column + half] * roots_[column * (Fft / span)];
                        const auto u = buffer[row + column];
                        buffer[row + column] = u + v;
                        buffer[row + column + half] = u - v;
                    }
                }
            }
            std::array<float, Mels> bands{};
            for (size_t bin = 0; bin < Bins; ++bin) {
                const float power = float(std::norm(buffer[bin]));
                if (floor) { powers_[bin * Frames + frame] = power; continue; }
                for (size_t index = 0; index < Mels; ++index) {
                    bands[index] += power * filters_[bin * Mels + index];
                }
            }
            if (!floor) for (size_t index = 0; index < Mels; ++index) mel[index * Frames + frame] = std::log(bands[index] + 1e-6f);
        }
        if (floor) {
            // Percentile .2 of 101 frames is order statistic 20. Preserve frame order.
            mel.fill(0);
            for (size_t bin = 0; bin < Bins; ++bin) {
                const float* column = powers_.data() + bin * Frames;
                std::array<float, Frames> ordered;
                std::copy_n(column, Frames, ordered.begin());
                std::nth_element(ordered.begin(), ordered.begin() + 20, ordered.end());
                const float floor_power = 1.25f * ordered[20];
                for (size_t band = 0; band < Mels; ++band) {
                    const float weight = filters_[bin * Mels + band];
                    if (!weight) continue;
                    for (size_t t = 0; t < Frames; ++t) {
                        mel[band * Frames + t] += weight * std::max(column[t] - floor_power, .1f * column[t]);
                    }
                }
            }
            for (float& value : mel) value = std::log(value + 1e-6f);
        }
    }

private:
    std::vector<float> powers_;
    std::array<float, Fft> window_{};
    std::array<float, Bins * Mels> filters_{};
    std::array<std::complex<double>, Fft / 2> roots_{};
    std::array<size_t, Fft> order_{};
};

class Runtime {
public:
    ~Runtime() {
        if (input_) api_->ReleaseValue(input_);
        if (memory_) api_->ReleaseMemoryInfo(memory_);
        if (session_) api_->ReleaseSession(session_);
        if (options_) api_->ReleaseSessionOptions(options_);
        if (env_) api_->ReleaseEnv(env_);
        if (library_) dlclose(library_);
    }

    void load(const char* model, std::array<float, Mels * Frames>& features) {
        library_ = dlopen("libonnxruntime.so", RTLD_NOW | RTLD_LOCAL);
        if (!library_) throw std::runtime_error(dlerror());
        auto found = reinterpret_cast<const OrtApiBase* (*)()>(dlsym(library_, "OrtGetApiBase"));
        if (!found) throw std::runtime_error("ONNX Runtime C API missing");
        const auto* base = found();
        version = base->GetVersionString();
        api_ = base->GetApi(17);
        if (!api_) throw std::runtime_error("ONNX Runtime API 17 unavailable");
        check(api_->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "wiley-next7", &env_));
        check(api_->CreateSessionOptions(&options_));
        check(api_->SetIntraOpNumThreads(options_, 1));
        check(api_->SetInterOpNumThreads(options_, 1));
        check(api_->SetSessionGraphOptimizationLevel(options_, ORT_ENABLE_EXTENDED));
        check(api_->CreateSession(env_, model, options_, &session_));
        check(api_->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &memory_));
        const int64_t shape[] = {1, 1, Mels, Frames};
        check(api_->CreateTensorWithDataAsOrtValue(memory_, features.data(), sizeof(features), shape, 4,
                ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &input_));
    }

    void infer(std::array<float, Embedding>& embedding) const {
        const char* inputs[]{"logmel"};
        const char* outputs[]{"embedding"};
        const OrtValue* values[]{input_};
        OrtValue* value = nullptr;
        check(api_->Run(session_, nullptr, inputs, values, 1, outputs, 1, &value));
        auto release = [this](OrtValue* v) { api_->ReleaseValue(v); };
        std::unique_ptr<OrtValue, decltype(release)> result(value, release);
        OrtTensorTypeAndShapeInfo* info = nullptr;
        check(api_->GetTensorTypeAndShape(value, &info));
        size_t elements = 0;
        const auto status = api_->GetTensorShapeElementCount(info, &elements);
        api_->ReleaseTensorTypeAndShapeInfo(info);
        check(status);
        if (elements != Embedding) throw std::runtime_error("Unexpected embedding shape");
        void* data = nullptr;
        check(api_->GetTensorMutableData(value, &data));
        std::copy_n(static_cast<const float*>(data), Embedding, embedding.data());
    }

    std::string version;

private:
    void check(OrtStatus* status) const {
        if (!status) return;
        const std::string message = api_->GetErrorMessage(status);
        api_->ReleaseStatus(status);
        throw std::runtime_error(message);
    }
    void* library_ = nullptr;
    const OrtApi* api_ = nullptr;
    OrtEnv* env_ = nullptr;
    OrtSessionOptions* options_ = nullptr;
    OrtSession* session_ = nullptr;
    OrtMemoryInfo* memory_ = nullptr;
    OrtValue* input_ = nullptr;
};

class Head {
public:
    explicit Head(std::istream& input) : vectors_((2 + 386) * Embedding) {
        if (!input.read(reinterpret_cast<char*>(vectors_.data()), vectors_.size()*sizeof(float)))
            throw std::runtime_error("Incomplete reference bank");
    }
    float score(const std::array<float, Embedding>& embedding) const {
        float norm = 0;
        for (const float v : embedding) norm += v*v;
        const float scale = 1.f / std::max(std::sqrt(norm), 1e-8f);
        float positive = -2, negative = -2;
        for (size_t row = 0; row < vectors_.size() / Embedding; ++row) {
            const float* v = vectors_.data() + row * Embedding;
            float dot = 0;
            for (size_t i=0; i<Embedding; ++i) dot += embedding[i] * v[i];
            float& best = row < 2 ? positive : negative;
            best = std::max(best, dot*scale);
        }
        return 2.f * (positive - negative);
    }
private:
    std::vector<float> vectors_;
};
} // namespace wiley_plix
