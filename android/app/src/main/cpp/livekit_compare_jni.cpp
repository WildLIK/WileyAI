#include "onnxruntime_c_api.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <dlfcn.h>
#include <jni.h>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// Same streaming signature and 25-block warmup as the validated NEXT 15 bench.
namespace {
struct LiveKit {

    void* library = nullptr;
    const OrtApi* api = nullptr;
    OrtEnv* env=nullptr;
    OrtSession* session=nullptr;
    OrtMemoryInfo* memory=nullptr;
    std::vector<std::string> input_storage,output_storage;
    std::vector<const char*> inputs,outputs;
    std::vector<OrtValue*> values;
    std::vector<std::pair<size_t, ONNXTensorElementDataType>> state_layout;
    float chunk[1280]{};
    float last_score=0;
    void check(OrtStatus* status) {
        if(!status)return;
        std::string error=api->GetErrorMessage(status);
        api->ReleaseStatus(status);
        throw std::runtime_error(error);
    }
    void init(const char* path) {
        library = dlopen("libonnxruntime.so", RTLD_NOW | RTLD_LOCAL);
        if (!library) throw std::runtime_error("ORT library");
        auto get = reinterpret_cast<const OrtApiBase* (*)()>(dlsym(library, "OrtGetApiBase"));
        if (!get) throw std::runtime_error("ORT symbol");
        api = get()->GetApi(17);
        if(!api) throw std::runtime_error("ORT ABI");
        check(api->CreateEnv(ORT_LOGGING_LEVEL_WARNING,"next14",&env));
        OrtSessionOptions* opt=nullptr;
        check(api->CreateSessionOptions(&opt));
        check(api->SetIntraOpNumThreads(opt,1));
        check(api->SetInterOpNumThreads(opt,1));
        check(api->AddSessionConfigEntry(opt,"mlas.disable_kleidiai","1"));
        OrtStatus* loaded = api->CreateSession(env,path,opt,&session);
        api->ReleaseSessionOptions(opt);
        check(loaded);
        check(api->CreateCpuMemoryInfo(OrtArenaAllocator,OrtMemTypeDefault,&memory));
        OrtAllocator* allocator=nullptr;
        check(api->GetAllocatorWithDefaultOptions(&allocator));
        size_t ni=0,no=0;
        check(api->SessionGetInputCount(session,&ni));
        check(api->SessionGetOutputCount(session,&no));
        if(ni!=no) throw std::runtime_error("ORT state contract");
        for(size_t i=0;i<ni;++i) {
            char* name=nullptr;
            check(api->SessionGetInputName(session,i,allocator,&name));
            input_storage.emplace_back(name);
            check(api->AllocatorFree(allocator,name));
            OrtTypeInfo* type=nullptr;
            check(api->SessionGetInputTypeInfo(session,i,&type));
            const OrtTensorTypeAndShapeInfo* shape=nullptr;
            check(api->CastTypeInfoToTensorInfo(type,&shape));
            size_t dimensions=0,count=0;
            ONNXTensorElementDataType data_type;
            check(api->GetDimensionsCount(shape,&dimensions));
            std::vector<int64_t> lengths(dimensions);
            check(api->GetDimensions(shape,lengths.data(),dimensions));
            check(api->GetTensorShapeElementCount(shape,&count));
            check(api->GetTensorElementType(shape,&data_type));
            api->ReleaseTypeInfo(type);
            OrtValue* tensor=nullptr;
            if(i==0) {
                if(input_storage.back()!="chunk"||count!=1280) throw std::runtime_error("ORT PCM contract");
                check(api->CreateTensorWithDataAsOrtValue(memory,chunk,sizeof(chunk),lengths.data(),dimensions,data_type,&tensor));
            } else {
                check(api->CreateTensorAsOrtValue(allocator,lengths.data(),dimensions,data_type,&tensor));
                void* raw=nullptr;
                check(api->GetTensorMutableData(tensor,&raw));
                if(data_type!=ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64 && data_type!=ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT)
                    throw std::runtime_error("ORT state dtype");
                state_layout.emplace_back(count, data_type);
                std::memset(raw,0,count*(data_type==ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64?8:4));
            }
            values.push_back(tensor);
        }
        output_storage.emplace_back("score");
        for(size_t i=1;i<ni;++i) output_storage.push_back(input_storage[i]+"_out");
        for(auto& name:input_storage) inputs.push_back(name.c_str());
        for(auto& name:output_storage) outputs.push_back(name.c_str());
        reset();
    }
    void reset() {
        for (size_t i = 1; i < values.size(); ++i) {
            const auto [count, type] = state_layout[i - 1];
            void* data = nullptr;
            check(api->GetTensorMutableData(values[i], &data));
            std::memset(data, 0, count * (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64 ? sizeof(int64_t) : sizeof(float)));
        }
        int16_t silence[1280]{};
        for (int i = 0; i < 25; ++i) step(silence);
    }
    ~LiveKit() {
        if (api) {
            for (auto* value : values) api->ReleaseValue(value);
            if (memory) api->ReleaseMemoryInfo(memory);
            if (session) api->ReleaseSession(session);
            if (env) api->ReleaseEnv(env);
        }
        if (library) dlclose(library);
    }
    float step(const int16_t* pcm) {
        std::transform(pcm,pcm+1280,chunk,[](int16_t v){return v/32768.f;});
        std::vector<OrtValue*> got(outputs.size(),nullptr);
        check(api->Run(session,nullptr,inputs.data(),values.data(),values.size(),outputs.data(),outputs.size(),got.data()));
        void* raw=nullptr;
        check(api->GetTensorMutableData(got[0],&raw));
        last_score=*static_cast<float*>(raw);
        api->ReleaseValue(got[0]);
        for(size_t i=1;i<values.size();++i) {
            api->ReleaseValue(values[i]);
            values[i]=got[i];
        }
        return last_score;
    }
};
}

extern "C" JNIEXPORT jlong JNICALL
Java_ru_wildlik_wileyai_mobile_WakeComparison_open(JNIEnv* env, jclass, jstring path) {
    if (!path) return 0;
    const char* chars = env->GetStringUTFChars(path, nullptr);
    if (!chars) return 0;
    jlong handle = 0;
    try {
        auto stream = std::make_unique<LiveKit>();
        stream->init(chars);
        handle = reinterpret_cast<jlong>(stream.release());
    } catch (...) {}
    env->ReleaseStringUTFChars(path, chars);
    return handle;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_ru_wildlik_wileyai_mobile_WakeComparison_reset(JNIEnv*, jclass, jlong handle) {
    if (!handle) return JNI_FALSE;
    try {
        reinterpret_cast<LiveKit*>(handle)->reset();
        return JNI_TRUE;
    } catch (...) { return JNI_FALSE; }
}

extern "C" JNIEXPORT jfloat JNICALL
Java_ru_wildlik_wileyai_mobile_WakeComparison_score(JNIEnv* env, jclass, jlong handle, jshortArray pcm) {
    if (!handle || !pcm || env->GetArrayLength(pcm) != 1280) return std::numeric_limits<float>::quiet_NaN();
    jshort block[1280];
    env->GetShortArrayRegion(pcm, 0, 1280, block);
    if (env->ExceptionCheck()) return std::numeric_limits<float>::quiet_NaN();
    try {
        return reinterpret_cast<LiveKit*>(handle)->step(block);
    } catch (...) { return std::numeric_limits<float>::quiet_NaN(); }
}

extern "C" JNIEXPORT void JNICALL
Java_ru_wildlik_wileyai_mobile_WakeComparison_close(JNIEnv*, jclass, jlong handle) {
    delete reinterpret_cast<LiveKit*>(handle);
}
