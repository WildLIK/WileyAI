// Host JNI lifetime test double, compiled against the pinned real llama.h.
// Never linked into an APK; no GGUF weights or language inference.
#include <llama.h>
#include <jni.h>
#include <atomic>
#include <chrono>
#include <thread>
#include <vector>
#include <string>
#include <stdexcept>
struct llama_vocab {};
struct llama_model { llama_vocab vocab;bool slow=false,consumed=false; };
struct llama_context { llama_model *model;llama_context_params params;int generated=0; };
struct FakeSampler { bool grammar=false;std::vector<llama_sampler *> children; };
static std::atomic<int> loads{0},frees{0},contexts{0},context_frees{0},models_now{0},contexts_now{0},entered{0};
extern "C" {
void llama_backend_init() {}
void llama_log_set(ggml_log_callback,void *) {}
llama_model_params llama_model_default_params(){return {};}
llama_context_params llama_context_default_params(){return {};}
llama_sampler_chain_params llama_sampler_chain_default_params(){return {};}
llama_model *llama_model_load_from_file(const char *path,llama_model_params params){
    if(std::string(path)=="bad")return nullptr;
    if(std::string(path)=="slow_load"){entered=1;while(params.progress_callback(.5f,params.progress_callback_user_data))std::this_thread::sleep_for(std::chrono::milliseconds(1));return nullptr;}
    if(++models_now!=1)throw std::runtime_error("duplicate weights");loads++;auto m=new llama_model;m->slow=std::string(path)=="slow_decode";return m;
}
void llama_model_free(llama_model *m){models_now--;frees++;delete m;}
llama_context *llama_init_from_model(llama_model *model,llama_context_params params){
    if(params.n_ctx!=2048 || params.n_batch!=256 || params.n_threads!=4)throw std::runtime_error("context config changed");
    if(++contexts_now!=1)throw std::runtime_error("overlapping contexts");contexts++;return new llama_context{model,params,0};
}
void llama_free(llama_context *ctx){contexts_now--;context_frees++;delete ctx;}
const llama_vocab *llama_model_get_vocab(const llama_model *m){return &m->vocab;}
int32_t llama_tokenize(const llama_vocab *,const char *,int32_t length,llama_token *tokens,int32_t max,bool,bool){if(!tokens || max<length)return -length;for(int i=0;i<length;i++)tokens[i]=10;return length;}
llama_batch llama_batch_get_one(llama_token *tokens,int32_t n){llama_batch b={};b.token=tokens;b.n_tokens=n;return b;}
int32_t llama_decode(llama_context *ctx,llama_batch batch){
    if(ctx->model->slow&&!ctx->model->consumed){ctx->model->consumed=true;entered=2;while(!ctx->params.abort_callback(ctx->params.abort_callback_data))std::this_thread::sleep_for(std::chrono::milliseconds(1));return 1;}
    if(ctx->params.abort_callback(ctx->params.abort_callback_data))return 1;
    if(batch.token[0]!=10)ctx->generated++;return 0;
}
llama_sampler *llama_sampler_init_greedy(){return new llama_sampler{nullptr,new FakeSampler};}
llama_sampler *llama_sampler_chain_init(llama_sampler_chain_params){return llama_sampler_init_greedy();}
llama_sampler *llama_sampler_init_grammar(const llama_vocab *,const char *text,const char *){if(std::string(text)=="bad")return nullptr;auto s=llama_sampler_init_greedy();static_cast<FakeSampler *>(s->ctx)->grammar=true;return s;}
void llama_sampler_chain_add(llama_sampler *chain,llama_sampler *child){auto c=static_cast<FakeSampler *>(chain->ctx);c->children.push_back(child);c->grammar|=static_cast<FakeSampler *>(child->ctx)->grammar;}
void llama_sampler_free(llama_sampler *s){auto f=static_cast<FakeSampler *>(s->ctx);for(auto child:f->children)llama_sampler_free(child);delete f;delete s;}
llama_token llama_sampler_sample(llama_sampler *s,llama_context *ctx,int32_t){return ctx->generated?3:static_cast<FakeSampler *>(s->ctx)->grammar?2:1;}
bool llama_vocab_is_eog(const llama_vocab *,llama_token t){return t==3;}
int32_t llama_token_to_piece(const llama_vocab *,llama_token t,char *buffer,int32_t length,int32_t,bool){if(length<1)return -1;buffer[0]=t==2?'J':'G';return 1;}
JNIEXPORT jlongArray JNICALL Java_ru_wildlik_wileyai_mobile_C8NativeProbe_stats(JNIEnv *env,jclass){jlong v[]={loads.load(),frees.load(),contexts.load(),context_frees.load(),models_now.load(),contexts_now.load(),entered.load()};auto a=env->NewLongArray(7);env->SetLongArrayRegion(a,0,7,v);return a;}
}
