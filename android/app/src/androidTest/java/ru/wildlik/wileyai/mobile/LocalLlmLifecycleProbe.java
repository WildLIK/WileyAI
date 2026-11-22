package ru.wildlik.wileyai.mobile;

import android.content.Context;
import org.json.*;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Explicit owner-run probe. Uses installed weights only; no tools/history/settings writes. */
final class LocalLlmLifecycleProbe {
    static String run(Context context)throws Exception {
        Path path=LlmModels.readActive(context.getFilesDir().toPath().resolve("llm-models"));
        if(path==null)throw new AssertionError("Сначала установите модель вручную; проба не скачивает файлы");
        LocalLlmRuntime runtime=LocalLlmRuntime.get(context);runtime.profileChanged();
        runtime.session.maintenance("probe_reset",()->{}).get(100,TimeUnit.SECONDS);
        JSONArray samples=new JSONArray();long loads=-1;
        try {
            for(int i=0;i<5;i++) {
                String grammar=i==3?StructuredActionAdapter.grammar(List.of(),1):null;
                String prompt=i==3?"<|im_start|>system\nВерни только JSON с steps=[] и reply=4. /no_think<|im_end|>\n<|im_start|>user\n2+2?<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n":LocalLlm.prompt(List.of(new LocalChatRepository.Message("user","Сколько будет 2+2? Кратко.")));
                LocalModelSession.Output output;
                if(i<3) {
                    // BrainController creates/closes a provider per turn: this
                    // must not become a hidden load-per-request boundary again.
                    try(LocalProvider provider=new LocalProvider(context)) {
                        BrainProvider.Completion reply=provider.complete(List.of(java.util.Map.of("role","system","content","Ответь кратко. /no_think"),java.util.Map.of("role","user","content","Сколько будет 2+2?")),List.of(),false,new BrainProvider.Cancellation(),text->{});
                        output=new LocalModelSession.Output(reply.text(),false,runtime.session.latest());
                    }
                } else output=runtime.session.generate(LocalLlmRuntime.model(path),prompt,grammar,cold->{},text->{}).result.get(100,TimeUnit.SECONDS);
                LocalModelSession.Metrics m=output.metrics();
                if(output.stopped()||output.text().isBlank()||m.cold()!=(i==0))throw new AssertionError("cold/warm generation "+i);
                if(i==0)loads=m.loads();else if(m.loads()!=loads)throw new AssertionError("GGUF был загружен повторно");
                if(i==3)StructuredActionAdapter.parse(output.text(),List.of());
                samples.put(new JSONObject().put("index",i+1).put("native",true).put("cold",m.cold()).put("loads",m.loads()).put("unloads",m.unloads()).put("load_ms",m.loadMs()).put("context_ms",m.contextMs()).put("prompt_ms",m.promptMs()).put("generation_ms",m.generationMs()).put("total_ms",m.totalMs()).put("ttft_ms",m.firstTokenMs()).put("ram_before",m.ramBefore()).put("ram_after",m.ramAfter()).put("answer_characters",output.text().length()));
            }
            return samples.toString();
        } finally {runtime.session.maintenance("probe_done",()->{}).get(100,TimeUnit.SECONDS);}
    }
}
