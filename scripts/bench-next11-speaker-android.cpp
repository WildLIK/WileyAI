// Isolated local benchmark. It reads a public/synthetic fixture and never opens audio input.
#include "c-api.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {
using Clock=std::chrono::steady_clock;
double ms(Clock::duration elapsed) {
    return std::chrono::duration<double,std::milli>(elapsed).count();
}
double percentile(std::vector<double> v,double q) {
    std::sort(v.begin(),v.end());
    const double idx=q*(v.size()-1);
    return v[size_t(idx)] + (idx-std::floor(idx))*(v[size_t(std::ceil(idx))]-v[size_t(idx)]);
}
long value(const char* path,const std::string& field) {
    std::ifstream file(path);
    for(std::string line;std::getline(file,line);) {
        if(line.rfind(field+":",0)==0) return std::stol(line.substr(field.size()+1));
    }
    return -1;
}
void bench(const char* path,const char* fixture) {
    std::ifstream input(fixture,std::ios::binary);
    std::vector<int16_t> raw(3*16000);
    if(!input.read(reinterpret_cast<char*>(raw.data()),raw.size()*sizeof(int16_t))) {
        throw std::runtime_error("Expected 3s PCM16");
    }
    std::vector<float> pcm(raw.size());
    std::transform(raw.begin(),raw.end(),pcm.begin(),[](int16_t v){return v/32768.0f;});
    SherpaOnnxSpeakerEmbeddingExtractorConfig config{};
    config.model=path;
    config.num_threads=1;
    config.provider="cpu";
    const auto init=Clock::now();
    auto destroy=SherpaOnnxDestroySpeakerEmbeddingExtractor;
    std::unique_ptr<const SherpaOnnxSpeakerEmbeddingExtractor,decltype(destroy)> encoder(
        SherpaOnnxCreateSpeakerEmbeddingExtractor(&config),destroy);
    if(!encoder)throw std::runtime_error("Cannot initialize extractor");
    const auto load=ms(Clock::now()-init);
    long pss=value("/proc/self/smaps_rollup","Pss");
    std::cout<<"{\"load_ms\":"<<load<<",\"initial_pss_kib\":"<<pss<<",\"windows\":[";
    bool first=true;
    for(int n:{8000,16000,24000,32000,48000}){
        std::vector<double> times;
        std::vector<float> embedding;
        const auto cpu=std::clock();
        for(int i=0;i<31;i++){
            const auto before=Clock::now();
            auto close=SherpaOnnxDestroyOnlineStream;
            std::unique_ptr<const SherpaOnnxOnlineStream,decltype(close)> stream(
                SherpaOnnxSpeakerEmbeddingExtractorCreateStream(encoder.get()),close);
            if(!stream)throw std::runtime_error("Cannot create stream");
            SherpaOnnxOnlineStreamAcceptWaveform(stream.get(),16000,pcm.data(),n);
            SherpaOnnxOnlineStreamInputFinished(stream.get());
            if(!SherpaOnnxSpeakerEmbeddingExtractorIsReady(encoder.get(),stream.get())){
                throw std::runtime_error("Too few frames");
            }
            auto release=SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding;
            std::unique_ptr<const float,decltype(release)> e(
                SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding(encoder.get(),stream.get()),release);
            if(!e)throw std::runtime_error("Missing embedding");
            if(i==0){
                embedding.assign(e.get(),e.get()+SherpaOnnxSpeakerEmbeddingExtractorDim(encoder.get()));
            }else{
                times.push_back(ms(Clock::now()-before));
            }
        }
        const double cpuMs=1000.0*(std::clock()-cpu)/CLOCKS_PER_SEC;
        if(!first)std::cout<<',';
        first=false;
        std::cout<<"{\"seconds\":"<<n/16000.0<<",\"count\":"<<times.size()
            <<",\"p50_ms\":"<<percentile(times,.5)<<",\"p95_ms\":"<<percentile(times,.95)
            <<",\"batch_cpu_ms_including_warmup\":"<<cpuMs<<",\"fixture_embedding\":[";
        for(size_t i=0;i<embedding.size();i++){
            if(i)std::cout<<',';
            std::cout<<embedding[i];
        }
        std::cout<<"]}";
    }
    std::cout<<"],\"pss_kib\":"<<value("/proc/self/smaps_rollup","Pss")
        <<",\"peak_rss_kib\":"<<value("/proc/self/status","VmHWM")<<"}\n";
}
}
int main(int argc,char** argv){
    try {
        if(argc!=3)throw std::runtime_error("Usage: benchmark model.onnx synthetic.pcm");
        bench(argv[1],argv[2]);
    }catch(const std::exception& error){
        std::cerr<<error.what()<<"\n";
        return 1;
    }
}
