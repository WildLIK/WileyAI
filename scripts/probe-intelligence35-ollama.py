"""Actual installed Qwen, isolated history/catalog, fake Windows executors."""
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import argparse
import types
import zipfile
import time
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import providers

spec=importlib.util.spec_from_file_location('intel35',Path(__file__).with_name('benchmark-intelligence35.py'))
bench=importlib.util.module_from_spec(spec);spec.loader.exec_module(bench)
ORIGINAL_CHAT,ORIGINAL_STRUCTURED=providers.chat,providers.structured
records=[]
class Stream(httpx.AsyncByteStream):
    def __init__(self,inner,record): self.inner,self.record=inner,record
    async def __aiter__(self):
        pending=b'';content=''
        async for block in self.inner:
            pending+=block
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1)
                if not line:continue
                value=json.loads(line);delta=value.get('message',{}).get('content','')
                if delta:
                    content+=delta
                    self.record.setdefault('first_content_ms',round((time.perf_counter()-self.record['began'])*1000,2))
                    if re.search(r'[.!?](?:\s|$)',content):self.record.setdefault('first_sentence_ms',round((time.perf_counter()-self.record['began'])*1000,2))
                if value.get('done'):
                    self.record.update({key:value.get(key) for key in ('load_duration','prompt_eval_duration','prompt_eval_count','eval_duration','eval_count','total_duration','done_reason')})
            yield block
    async def aclose(self):await self.inner.aclose()
class Transport(httpx.AsyncBaseTransport):
    def __init__(self):self.inner=httpx.AsyncHTTPTransport()
    async def handle_async_request(self,request):
        payload=json.loads(request.content)
        record=dict(began=time.perf_counter(),structured='format' in payload,think=payload.get('think'),num_predict=payload.get('options',{}).get('num_predict'))
        records.append(record)
        response=await self.inner.handle_async_request(request)
        return httpx.Response(response.status_code,headers=response.headers,stream=Stream(response.stream,record))
    async def aclose(self):await self.inner.aclose()

def client(settings):return httpx.AsyncClient(base_url=settings.base_url+'/',timeout=httpx.Timeout(90,connect=3),trust_env=False,transport=Transport())

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',action='store_true');args=parser.parse_args()
    if args.baseline:
        # Replay only the changed routing boundary from the preserved source;
        # do not overwrite the checkout or downgrade any on-disk files.
        from core import api as api_module,app_discovery
        module=types.ModuleType('core._intel35_before');sys.modules[module.__name__]=module
        with zipfile.ZipFile('local/review/intelligence35/baseline-files.zip') as archive:
            exec(compile(archive.read('core/semantic_commands.py'),'baseline/semantic_commands.py','exec'),module.__dict__)
        api_module.semantic_commands=module
        app_discovery.purpose_key=lambda _:None
        app_discovery.ApplicationScanner.purpose_matches=lambda self,_:None
    before=httpx.get('http://127.0.0.1:11434/api/ps',timeout=3,trust_env=False).json()
    with tempfile.TemporaryDirectory(prefix='wiley-qwen35-') as folder:
        with bench.harness(Path(folder)) as (api,state):
            app=api.app
            app.state.store.patch_settings(dict(provider='ollama',base_url='http://127.0.0.1:11434',model='qwen3.5:4b',context_tokens=4096,response_tokens=256))
            async def chat(*args,**kw):
                if kw.get('output_schema') is None:state['ordinary']+=1
                async for part in ORIGINAL_CHAT(*args,**kw):yield part
            decisions=[]
            async def structured(*args,**kw):
                state['structured']+=1
                value=await ORIGINAL_STRUCTURED(*args,**kw);decisions.append(value);return value
            providers.chat,providers.structured,providers.client=chat,structured,client
            results=[]
            for text,kind in [('Расскажи в двух предложениях, почему Луна светится.','conversation'),('Открой мне Blender','open'),('Открой Яндекс Браузер','open'),('Воспроизведи музыку','media'),('Вот ты меня слышишь','conversation'),('Открой мне плеер','clarify'),('Хочу что-нибудь нарисовать','safe'),('Хочу поработать в Blender','safe')]:
                parameters={'name':'Яндекс Браузер' if 'Яндекс' in text else 'Blender'} if kind=='open' else {'action':'play','scope':'player'} if kind=='media' else {}
                at=len(records);decision_at=len(decisions);result=bench.run_case(api,state,dict(text=text,expected_type=kind,parameters=parameters));result['calls']=records[at:];result['decisions']=decisions[decision_at:];results.append(result)
    after=httpx.get('http://127.0.0.1:11434/api/ps',timeout=3,trust_env=False).json()
    for record in records:record.pop('began',None)
    output=dict(scope='real Qwen; synthetic inputs/catalog; Windows actions fake; context4096/output256; no TTS or physical microphone',before=before,after=after,results=results)
    output['baseline_replay']=args.baseline
    Path('local/review/intelligence35/ollama-before.json' if args.baseline else 'local/review/intelligence35/ollama.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
