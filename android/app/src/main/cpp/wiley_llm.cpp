#include <jni.h>
#include <llama.h>
#include <atomic>
#include <mutex>
#include <memory>
#include <string>
#include <vector>
#include <unordered_map>
#include <stdexcept>
#include <chrono>

using Clock = std::chrono::steady_clock;
static int64_t elapsed(Clock::time_point start) { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count(); }
struct Session {
    llama_model *model = nullptr;
    llama_context *context = nullptr;
    llama_sampler *sampler = nullptr;
    std::atomic<bool> stopped{false};
    std::mutex operation;
    int used = 0;
    int64_t tokenize_ns=0, prefill_ns=0, decode_ns=0;
    void finish() {
        if(sampler) { llama_sampler_free(sampler); sampler=nullptr; }
        if(context) { llama_free(context); context=nullptr; }
        used=0;
    }
    ~Session() { finish(); if(model) llama_model_free(model); }
};
static std::mutex registry_lock;
static std::unordered_map<jlong,std::shared_ptr<Session>> sessions;
static jlong next_id=1;
static std::once_flag initialized;
static void fail(JNIEnv *env, const char *message) { if(!env->ExceptionCheck())env->ThrowNew(env->FindClass("java/io/IOException"), message); }
static std::shared_ptr<Session> get(jlong id) {
    std::lock_guard<std::mutex> guard(registry_lock);
    auto found=sessions.find(id);
    if(found==sessions.end())throw std::runtime_error("Локальная сессия уже освобождена");
    return found->second;
}
static bool aborting(void *data) { return static_cast<Session *>(data)->stopped.load(); }
static bool loading(float,void *data) { return !aborting(data); }
static std::string bytes(JNIEnv *env,jbyteArray array) {
    if(!array)throw std::runtime_error("Не переданы данные запроса");
    int size=env->GetArrayLength(array);std::string value(size,'\0');env->GetByteArrayRegion(array,0,size,reinterpret_cast<jbyte *>(value.data()));
    if(env->ExceptionCheck())throw std::runtime_error("Не удалось прочитать данные запроса");
    return value;
}
extern "C" JNIEXPORT jlong JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_create(JNIEnv *env,jclass) {
    try {
        std::call_once(initialized,[]{llama_log_set([](ggml_log_level,const char *,void *){},nullptr);llama_backend_init();});
        auto session=std::make_shared<Session>();std::lock_guard<std::mutex> guard(registry_lock);jlong id=next_id++;sessions.emplace(id,session);return id;
    }catch(const std::exception &e){fail(env,e.what());return 0;}
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_load(JNIEnv *env,jclass,jlong id,jstring path) {
    try {
        auto s=get(id);std::lock_guard<std::mutex> guard(s->operation);
        if(s->model)throw std::runtime_error("Модель уже загружена");
        if(!path)throw std::runtime_error("Не указан файл модели");
        const char *file=env->GetStringUTFChars(path,nullptr);if(!file)return;
        std::string name;
        try{name=file;}catch(...){env->ReleaseStringUTFChars(path,file);throw;}
        env->ReleaseStringUTFChars(path,file);
        auto params=llama_model_default_params();params.n_gpu_layers=0;params.progress_callback=loading;params.progress_callback_user_data=s.get();
        s->model=llama_model_load_from_file(name.c_str(),params);
        if(!s->model)throw std::runtime_error("GGUF-модель не поддерживается, повреждена или загрузка остановлена");
    }catch(const std::exception &e){fail(env,e.what());}
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_prepare(JNIEnv *env,jclass,jlong id) {
    try {
        auto s=get(id);std::lock_guard<std::mutex> guard(s->operation);
        if(!s->model)throw std::runtime_error("Модель не загружена");
        s->finish();s->stopped.store(false);s->tokenize_ns=s->prefill_ns=s->decode_ns=0;
        auto config=llama_context_default_params();config.n_ctx=2048;config.n_batch=256;config.n_ubatch=128;
        config.n_threads=4;config.n_threads_batch=4;config.abort_callback=aborting;config.abort_callback_data=s.get();
        s->context=llama_init_from_model(s->model,config);
        if(!s->context)throw std::runtime_error("Не удалось выделить память для контекста модели");
        s->sampler=llama_sampler_init_greedy();if(!s->sampler)throw std::runtime_error("Не удалось создать sampler");
    }catch(const std::exception &e){fail(env,e.what());}
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_begin(JNIEnv *env,jclass,jlong id,jbyteArray prompt) {
    try {
        auto s=get(id);std::lock_guard<std::mutex> guard(s->operation);
        if(!s->context || !s->sampler)throw std::runtime_error("Контекст запроса не подготовлен");
        auto began=Clock::now();std::string text=bytes(env,prompt);auto vocab=llama_model_get_vocab(s->model);
        int size=-llama_tokenize(vocab,text.data(),text.size(),nullptr,0,true,true);
        if(size<1 || size>1700)throw std::runtime_error("Сообщение слишком длинное для контекста 2048 токенов. Сократите его или начните новый чат.");
        std::vector<llama_token> tokens(size);size=llama_tokenize(vocab,text.data(),text.size(),tokens.data(),size,true,true);
        s->tokenize_ns=elapsed(began);if(size<1)throw std::runtime_error("Не удалось прочитать текст модели");
        began=Clock::now();
        for(int offset=0;offset<size;offset+=256) {
            if(s->stopped.load())throw std::runtime_error("Ответ остановлен");
            int count=std::min(256,size-offset);
            if(llama_decode(s->context,llama_batch_get_one(tokens.data()+offset,count))!=0)throw std::runtime_error("Не удалось обработать запрос модели");
        }
        s->prefill_ns=elapsed(began);s->used=size;
    }catch(const std::exception &e){fail(env,e.what());}
}
extern "C" JNIEXPORT jbyteArray JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_next(JNIEnv *env,jclass,jlong id) {
    try {
        auto s=get(id);std::lock_guard<std::mutex> guard(s->operation);
        if(!s->context || !s->sampler)throw std::runtime_error("Контекст запроса не подготовлен");
        if(s->stopped.load() || s->used>=2047)return nullptr;
        auto began=Clock::now();auto vocab=llama_model_get_vocab(s->model);llama_token token=llama_sampler_sample(s->sampler,s->context,-1);
        if(llama_vocab_is_eog(vocab,token))return nullptr;
        std::vector<char> piece(256);int count=llama_token_to_piece(vocab,token,piece.data(),piece.size(),0,false);
        if(count<0){piece.resize(-count);count=llama_token_to_piece(vocab,token,piece.data(),piece.size(),0,false);}
        if(count<0 || llama_decode(s->context,llama_batch_get_one(&token,1))!=0)throw std::runtime_error("Не удалось продолжить ответ модели");
        s->decode_ns+=elapsed(began);s->used++;jbyteArray result=env->NewByteArray(count);
        if(result)env->SetByteArrayRegion(result,0,count,reinterpret_cast<jbyte *>(piece.data()));return result;
    }catch(const std::exception &e){fail(env,e.what());return nullptr;}
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_grammar(JNIEnv *env,jclass,jlong id,jbyteArray grammar) {
    try {
        auto s=get(id);std::lock_guard<std::mutex> guard(s->operation);
        if(!s->context || !s->sampler)throw std::runtime_error("Контекст запроса не подготовлен");
        std::string text=bytes(env,grammar);if(text.empty() || text.size()>32768)throw std::runtime_error("Invalid action grammar");
        using Sampler=std::unique_ptr<llama_sampler,decltype(&llama_sampler_free)>;
        Sampler rule(llama_sampler_init_grammar(llama_model_get_vocab(s->model),text.c_str(),"root"),llama_sampler_free);
        if(!rule)throw std::runtime_error("Не удалось подготовить JSON-грамматику");
        Sampler chain(llama_sampler_chain_init(llama_sampler_chain_default_params()),llama_sampler_free);
        if(!chain)throw std::runtime_error("Не удалось создать sampler");
        llama_sampler_chain_add(chain.get(),rule.get());rule.release();
        Sampler greedy(llama_sampler_init_greedy(),llama_sampler_free);if(!greedy)throw std::runtime_error("Не удалось создать sampler");
        llama_sampler_chain_add(chain.get(),greedy.get());greedy.release();
        llama_sampler_free(s->sampler);s->sampler=chain.release();
    }catch(const std::exception &e){fail(env,e.what());}
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_finish(JNIEnv *env,jclass,jlong id) {
    try{auto s=get(id);std::lock_guard<std::mutex> guard(s->operation);s->finish();}catch(const std::exception &e){fail(env,e.what());}
}
extern "C" JNIEXPORT jlongArray JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_timings(JNIEnv *env,jclass,jlong id) {
    try{auto s=get(id);std::lock_guard<std::mutex> guard(s->operation);jlong values[]={s->tokenize_ns,s->prefill_ns,s->decode_ns};auto result=env->NewLongArray(3);if(result)env->SetLongArrayRegion(result,0,3,values);return result;}catch(const std::exception &e){fail(env,e.what());return nullptr;}
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_cancel(JNIEnv *,jclass,jlong id) {
    try{get(id)->stopped.store(true);}catch(const std::exception &){ /* Already released: idempotent abort. */ }
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_close(JNIEnv *,jclass,jlong id) {
    std::shared_ptr<Session> removed;
    {std::lock_guard<std::mutex> guard(registry_lock);auto found=sessions.find(id);if(found==sessions.end())return;removed=found->second;removed->stopped.store(true);sessions.erase(found);}
    // An in-flight JNI call holds a shared reference; freed IDs are never reused.
}
