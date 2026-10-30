#include <jni.h>
#include <llama.h>
#include <atomic>
#include <mutex>
#include <memory>
#include <string>
#include <vector>
#include <stdexcept>

struct Session {
    llama_model *model = nullptr;
    llama_context *context = nullptr;
    llama_sampler *sampler = nullptr;
    std::atomic<bool> stopped{false};
    int used = 0;
    ~Session() { if(sampler) llama_sampler_free(sampler); if(context) llama_free(context); if(model) llama_model_free(model); }
};
static void fail(JNIEnv *env, const char *message) { env->ThrowNew(env->FindClass("java/io/IOException"), message); }
static bool aborting(void *data) { return static_cast<Session *>(data)->stopped.load(); }
static std::once_flag initialized;
extern "C" JNIEXPORT jlong JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_load(JNIEnv *env, jclass, jstring path) {
    try {
        std::call_once(initialized, [] { llama_log_set([](ggml_log_level, const char *, void *) {}, nullptr); llama_backend_init(); });
        auto session = std::make_unique<Session>();
        const char *file = env->GetStringUTFChars(path, nullptr);
        auto params = llama_model_default_params(); params.n_gpu_layers = 0;
        session->model = llama_model_load_from_file(file, params); env->ReleaseStringUTFChars(path, file);
        if(!session->model) throw std::runtime_error("GGUF-модель не поддерживается или повреждена");
        auto config = llama_context_default_params(); config.n_ctx = 2048; config.n_batch = 256; config.n_ubatch = 128;
        config.n_threads = 4; config.n_threads_batch = 4; config.abort_callback = aborting; config.abort_callback_data = session.get();
        session->context = llama_init_from_model(session->model, config);
        if(!session->context) throw std::runtime_error("Не удалось выделить память для модели");
        session->sampler = llama_sampler_init_greedy();
        return reinterpret_cast<jlong>(session.release());
    } catch(const std::exception &error) { fail(env, error.what()); return 0; }
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_begin(JNIEnv *env, jclass, jlong handle, jbyteArray prompt) {
    auto s = reinterpret_cast<Session *>(handle);
    try {
        int length = env->GetArrayLength(prompt); std::string text(length, '\0'); env->GetByteArrayRegion(prompt, 0, length, reinterpret_cast<jbyte *>(text.data()));
        auto vocab = llama_model_get_vocab(s->model);
        int size = -llama_tokenize(vocab, text.data(), length, nullptr, 0, true, true);
        if(size < 1 || size > 1700) throw std::runtime_error("Сообщение слишком длинное для контекста 2048 токенов. Сократите его или начните новый чат.");
        std::vector<llama_token> tokens(size); size = llama_tokenize(vocab, text.data(), length, tokens.data(), size, true, true);
        if(size < 1) throw std::runtime_error("Не удалось прочитать текст модели");
        for(int offset = 0; offset < size; offset += 256) {
            if(s->stopped.load()) throw std::runtime_error("Ответ остановлен");
            int count = std::min(256, size - offset);
            if(llama_decode(s->context, llama_batch_get_one(tokens.data() + offset, count)) != 0) throw std::runtime_error("Не удалось обработать запрос модели");
        }
        s->used = size;
    } catch(const std::exception &error) { fail(env, error.what()); }
}
extern "C" JNIEXPORT jbyteArray JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_next(JNIEnv *env, jclass, jlong handle) {
    auto s = reinterpret_cast<Session *>(handle);
    try {
        if(s->stopped.load() || s->used >= 2047) return nullptr;
        auto vocab = llama_model_get_vocab(s->model); llama_token token = llama_sampler_sample(s->sampler, s->context, -1);
        if(llama_vocab_is_eog(vocab, token)) return nullptr;
        std::vector<char> piece(256); int count = llama_token_to_piece(vocab, token, piece.data(), piece.size(), 0, false);
        if(count < 0) { piece.resize(-count); count = llama_token_to_piece(vocab, token, piece.data(), piece.size(), 0, false); }
        if(count < 0 || llama_decode(s->context, llama_batch_get_one(&token, 1)) != 0) throw std::runtime_error("Не удалось продолжить ответ модели");
        s->used++; jbyteArray result = env->NewByteArray(count); env->SetByteArrayRegion(result, 0, count, reinterpret_cast<jbyte *>(piece.data())); return result;
    } catch(const std::exception &error) { fail(env, error.what()); return nullptr; }
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_grammar(JNIEnv *env, jclass, jlong handle, jbyteArray grammar) {
    auto s = reinterpret_cast<Session *>(handle);
    try {
        int length=env->GetArrayLength(grammar);if(length<1||length>32768)throw std::runtime_error("Invalid action grammar");
        std::string text(length,'\0');env->GetByteArrayRegion(grammar,0,length,reinterpret_cast<jbyte *>(text.data()));
        llama_sampler *rule=llama_sampler_init_grammar(llama_model_get_vocab(s->model),text.c_str(),"root");
        if(!rule)throw std::runtime_error("Не удалось подготовить JSON-грамматику");
        llama_sampler *chain=llama_sampler_chain_init(llama_sampler_chain_default_params());
        llama_sampler_chain_add(chain,rule);llama_sampler_chain_add(chain,llama_sampler_init_greedy());
        llama_sampler_free(s->sampler);s->sampler=chain;
    }catch(const std::exception &error){fail(env,error.what());}
}
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_cancel(JNIEnv *, jclass, jlong handle) { reinterpret_cast<Session *>(handle)->stopped.store(true); }
extern "C" JNIEXPORT void JNICALL Java_ru_wildlik_wileyai_mobile_LocalLlmNative_close(JNIEnv *, jclass, jlong handle) { delete reinterpret_cast<Session *>(handle); }
