// Isolated NEXT 7 numerical and resource probe for the ONNX Runtime in the APK.
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

#include "../android/app/src/main/cpp/plix_observer.hpp"

namespace {
using namespace wiley_plix;
using Clock = std::chrono::steady_clock;
volatile std::sig_atomic_t stopped = 0;

void request_stop(int) { stopped = 1; }

double ms(Clock::duration elapsed) { return std::chrono::duration<double, std::milli>(elapsed).count(); }

long memory_kib(const char* key, const char* path) {
    std::ifstream stream(path);
    std::string line;
    const std::string prefix = std::string(key) + ':';
    while (std::getline(stream, line)) {
        if (line.compare(0, prefix.size(), prefix) == 0) return std::stol(line.substr(prefix.size()));
    }
    return -1;
}

double process_ms() {
    timespec time{};
    if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &time) != 0) throw std::runtime_error("CPU clock unavailable");
    return (double(time.tv_sec) * 1000 + double(time.tv_nsec) / 1e6);
}

double percentile(std::vector<double> values, double fraction) {
    if (values.empty()) return 0;
    std::sort(values.begin(), values.end());
    const double index = fraction * (values.size() - 1);
    const size_t low = size_t(index), high = size_t(std::ceil(index));
    return values[low] + (values[high] - values[low]) * (index - low);
}

int run(const char* model, const char* fixtures, int iterations, bool paced, const char* head_path) {
    std::ifstream stream(fixtures, std::ios::binary);
    Frontend frontend(stream);
    std::unique_ptr<Head> head;
    if (head_path) {
        std::ifstream bank(head_path, std::ios::binary);
        head = std::make_unique<Head>(bank);
    }
    std::array<uint32_t, 1> count{};
    read(stream, count);
    if (count[0] == 0 || count[0] > 32) throw std::runtime_error("Invalid fixture length");
    std::vector<Clip> clips(count[0]);
    std::vector<float> expected_scores;
    for (auto& clip : clips) {
        read(stream, clip.pcm);
        read(stream, clip.mel);
        read(stream, clip.embedding);
        if (head) { std::array<float, 1> reference{}; read(stream, reference); expected_scores.push_back(reference[0]); }
    }
    std::array<float, Mels * Frames> features{};
    std::array<float, Embedding> embedding{};
    const auto init = Clock::now();
    Runtime runtime;
    runtime.load(model, features);
    const double load = ms(Clock::now() - init);
    const long pss_loaded = memory_kib("Pss", "/proc/self/smaps_rollup");
    double score_error = 0;
    double feature_error = 0, embedding_error = 0, min_cosine = 1;
    for (const auto& clip : clips) {
        frontend.calculate(clip.pcm, features, bool(head));
        runtime.infer(embedding);
        for (size_t i = 0; i < features.size(); ++i) feature_error = std::max(feature_error, std::abs(double(features[i] - clip.mel[i])));
        if (head) score_error = std::max(score_error, std::abs(double(head->score(embedding) - expected_scores[&clip - clips.data()])));
        double dot = 0, norm = 0, expected_norm = 0;
        for (size_t i = 0; i < Embedding; ++i) {
            const double got = embedding[i], expected = clip.embedding[i];
            embedding_error = std::max(embedding_error, std::abs(got - expected));
            dot += got * expected;
            norm += got * got;
            expected_norm += expected * expected;
        }
        min_cosine = std::min(min_cosine, dot / std::sqrt(norm * expected_norm));
    }
    if (!(feature_error < .002 && embedding_error < .005 && min_cosine > .9999 && score_error < 1e-4)) {
        throw std::runtime_error("Android/Windows numerical mismatch");
    }
    std::vector<double> frontend_time, inference_time, score_time, window_time;
    frontend_time.reserve(iterations);
    inference_time.reserve(iterations);
    window_time.reserve(iterations);
    auto began = Clock::now();
    const auto cpu = process_ms();
    long pss_peak_sampled = pss_loaded;
    for (int i = 0; i < iterations && !stopped; ++i) {
        if (paced) std::this_thread::sleep_until(began + std::chrono::milliseconds(80 * i));
        if (stopped) break;
        const auto start = Clock::now();
        frontend.calculate(clips[i % clips.size()].pcm, features, bool(head));
        const auto middle = Clock::now();
        runtime.infer(embedding);
        const auto inferred = Clock::now();
        if (head) { volatile float decision_score = head->score(embedding); (void)decision_score; }
        const auto end = Clock::now();
        frontend_time.push_back(ms(middle - start));
        inference_time.push_back(ms(inferred - middle));
        score_time.push_back(ms(end - inferred));
        window_time.push_back(ms(end - start));
        if (i % 63 == 0) pss_peak_sampled = std::max(pss_peak_sampled, memory_kib("Pss", "/proc/self/smaps_rollup"));
    }
    const auto cpu_ms = process_ms() - cpu;
    const double wall_ms = ms(Clock::now() - began);
    const long pss_final = memory_kib("Pss", "/proc/self/smaps_rollup");
    pss_peak_sampled = std::max(pss_peak_sampled, pss_final);
    const long rss_peak = memory_kib("VmHWM", "/proc/self/status");
    std::cout << "{\"runtime\":\"" << runtime.version << "\",\"clips\":" << clips.size()
              << ",\"load_ms\":" << load << ",\"feature_max_abs\":" << feature_error << ",\"embedding_max_abs\":" << embedding_error
              << ",\"score_max_abs\":" << score_error << ",\"inference_p95_ms\":" << percentile(inference_time,.95)
              << ",\"score_p50_ms\":" << percentile(score_time,.5) << ",\"score_p95_ms\":" << percentile(score_time,.95)
              << ",\"min_cosine\":" << min_cosine << ",\"iterations\":" << window_time.size() << ",\"cancelled\":" << (stopped ? "true" : "false")
              << ",\"frontend_p50_ms\":" << percentile(frontend_time, .5) << ",\"inference_p50_ms\":" << percentile(inference_time, .5)
              << ",\"window_p50_ms\":" << percentile(window_time, .5) << ",\"window_p95_ms\":" << percentile(window_time, .95)
              << ",\"wall_ms\":" << wall_ms << ",\"cpu_ms\":" << cpu_ms << ",\"peak_rss_kib\":" << rss_peak
              << ",\"pss_loaded_kib\":" << pss_loaded << ",\"pss_final_kib\":" << pss_final
              << ",\"sampled_peak_pss_kib\":" << pss_peak_sampled << "}\n";
    return 0;
}
}

int main(int argc, char** argv) {
    try {
        if (argc != 5 && argc != 6) throw std::runtime_error("usage: probe model.onnx fixtures.bin iterations paced|fast [H2-bank.bin]");
        const int iterations = std::stoi(argv[3]);
        if (iterations < 0 || iterations > 2400) throw std::runtime_error("Invalid number of windows");
        std::signal(SIGTERM, request_stop);
        std::signal(SIGINT, request_stop);
        return run(argv[1], argv[2], iterations, std::string(argv[4]) == "paced", argc == 6 ? argv[5] : nullptr);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
