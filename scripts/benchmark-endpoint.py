import argparse, ctypes as c, json, sys, time, wave, math
from pathlib import Path
import numpy as np
import psutil
from scipy.signal import resample_poly, butter, sosfilt

ROOT=Path('local/review/voice33'); ROOT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/'python'))

def prepare():
 import hashlib, httpx
 files={
  'ten_vad.dll':('https://raw.githubusercontent.com/TEN-framework/ten-vad/d68ab71c8d5fbd8f98e97ae7c9986af76b5d72b1/lib/Windows/x64/ten_vad.dll','38937f5604fa93a7941db7b9326992b792fa3731ebf9353973b3234457c6064b'),
  'ten-LICENSE':('https://raw.githubusercontent.com/TEN-framework/ten-vad/d68ab71c8d5fbd8f98e97ae7c9986af76b5d72b1/LICENSE','03d862b922867b8c3406a0c17791e256ed3d76f197d88c1996c4aebfb79f688e'),
  'smart-turn-v3.2-cpu.onnx':('https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx','2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f'),
 }
 print('Explicit benchmark preparation: downloading TEN research DLL/license and optional Smart Turn weights to',ROOT,flush=True)
 with httpx.Client(follow_redirects=True,timeout=90) as client:
  for name,(url,digest) in files.items():
   target=ROOT/name
   if not target.exists():
    response=client.get(url);response.raise_for_status();target.write_bytes(response.content)
   if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Benchmark artifact checksum mismatch: '+name)

def read(path):
 with wave.open(str(path)) as f:
  sr=f.getframerate(); a=np.frombuffer(f.readframes(f.getnframes()),'<i2').astype(np.float32)/32768
  a=a.reshape(-1,f.getnchannels()).mean(axis=1)
  return resample_poly(a,16000//math.gcd(sr,16000),sr//math.gcd(sr,16000)).astype(np.float32)

def corpus():
 a=read('tests/fixtures/endpoint/command.wav')
 voiced=np.flatnonzero(np.abs(a)>.01);a=a[max(0,voiced[0]-160):voiced[-1]+161]
 b=read('tests/fixtures/endpoint/sentence.wav'); v=np.flatnonzero(np.abs(b)>.01); b=b[v[0]:v[-1]+1]
 cases=[]; rng=np.random.default_rng(330)
 def add(name,parts,noise=None):
  duration=sum(len(p) if isinstance(p,np.ndarray) else int(p*16000) for p in parts)
  audio=np.zeros(duration,np.float32);ranges=[]; at=0
  for part in parts:
   if isinstance(part,np.ndarray): audio[at:at+len(part)]=part; ranges.append([at/16000,(at+len(part))/16000]);at+=len(part)
   else:at+=int(part*16000)
  if noise=='music':
   t=np.arange(duration)/16000; music=sum(np.sin(2*np.pi*f*t+np.sin(t*.7)) for f in [130.8,164.8,196,261.6])*.009
   music*=.7+.3*np.sin(t*3.2)**2;audio+=music.astype(np.float32)
  if noise=='fan':audio+=sosfilt(butter(2,250,fs=16000,output='sos'),rng.normal(0,.15,duration)).astype(np.float32)
  path=ROOT/(name+'.wav')
  with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes((np.clip(audio,-1,1)*32767).astype('<i2').tobytes())
  cases.append({'name':name,'path':str(path),'speech':ranges,'duration':duration/16000})
 add('short',[1.,a,3.]);add('short_music',[1.,a,3.],'music');add('mid_pause',[1.,b[:len(b)//2],.75,b[len(b)//2:],3.])
 add('long',[1.,np.tile(b,10),3.]);add('fan',[8.],'fan');add('click',[1.,np.ones(320,np.float32)*.4,3.]); cases[-1]['speech']=[]
 add('silence',[6.]);add('music',[10.],'music'); add('short_fan',[1.,a,3.],'fan')
 (ROOT/'corpus.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
 return cases

def run(engine):
 start=time.perf_counter();process=psutil.Process();baseline=process.memory_info().rss; cpu0=time.process_time()
 if engine=='ten':
  import hashlib
  if hashlib.sha256((ROOT/'ten_vad.dll').read_bytes()).hexdigest()!='38937f5604fa93a7941db7b9326992b792fa3731ebf9353973b3234457c6064b':raise ValueError('TEN DLL checksum mismatch')
  dll=c.CDLL(str((ROOT/'ten_vad.dll').resolve()));dll.ten_vad_create.argtypes=[c.POINTER(c.c_void_p),c.c_size_t,c.c_float];dll.ten_vad_process.argtypes=[c.c_void_p,c.POINTER(c.c_int16),c.c_size_t,c.POINTER(c.c_float),c.POINTER(c.c_int)];hop=256
 elif engine=='webrtc':import webrtcvad;hop=320
 else:
  import onnxruntime as ort
  opts=ort.SessionOptions();opts.intra_op_num_threads=1;opts.inter_op_num_threads=1
  sess=ort.InferenceSession(str(Path('assets/voice/silero_vad_v5.onnx')),sess_options=opts,providers=['CPUExecutionProvider']);hop=512
 initialization=(time.perf_counter()-start)*1000; cases=json.loads((ROOT/'corpus.json').read_text());out=[]; peak=process.memory_info().rss; cpu_start=time.process_time();ticks=[]
 for case in cases:
  audio=read(case['path']);probs=[]
  if engine=='ten':
   handle=c.c_void_p();assert dll.ten_vad_create(c.byref(handle),hop,.5)==0
  elif engine=='webrtc':vad=webrtcvad.Vad(2)
  else:state=np.zeros((2,1,128),np.float32);context=np.zeros((1,64),np.float32)
  for at in range(0,len(audio),hop):
   chunk=np.pad(audio[at:at+hop],(0,max(0,at+hop-len(audio))));t=time.perf_counter()
   if engine=='ten':
    pcm=(np.clip(chunk,-1,1)*32767).astype(np.int16);p=c.c_float();flag=c.c_int();assert dll.ten_vad_process(handle,pcm.ctypes.data_as(c.POINTER(c.c_int16)),hop,c.byref(p),c.byref(flag))==0;prob=p.value
   elif engine=='webrtc':prob=float(vad.is_speech((np.clip(chunk,-1,1)*32767).astype('<i2').tobytes(),16000))
   else:
    x=np.concatenate([context,chunk[None,:]],axis=1);value,state=sess.run(None,{'input':x,'state':state,'sr':np.array(16000,dtype=np.int64)});context=x[:,-64:];prob=float(value[0][0])
   ticks.append((time.perf_counter()-t)*1000);probs.append(prob)
   peak=max(peak,process.memory_info().rss)
  if engine=='ten':dll.ten_vad_destroy(c.byref(handle))
  # Same 700 ms endpoint policy, 128 ms minimum speech. These labels describe
  # inserted synthetic speech spans, not a human-annotated microphone corpus.
  sending=[]; active=False;spoken=0;last=0;fp=fn=voice=background=0
  for i,p in enumerate(probs):
   end=(i+1)*hop/16000;truth=any(a<=end<=b for a,b in case['speech']);positive=p>=.5
   if truth:voice+=1;fn+=not positive
   else:background+=1;fp+=positive
   if positive: active=True;spoken+=hop/16000;last=end
   if active and end-last>=.7:
    if spoken>=.128:sending.append(end)
    active=False;spoken=0
  expected=case['speech'][-1][1] if case['speech'] else None
  out.append({**case,'hop':hop,'probabilities':probs,'sent':sending,'speech_frames':voice,'missed_frames':fn,'noise_frames':background,'false_frames':fp,'endpoint_delay_ms':round((sending[-1]-expected)*1000,1) if expected and sending else None,'cut':bool(expected and any(x<expected-.2 for x in sending)),'missed':bool(expected and not sending),'false_turns':len(sending) if not expected else 0})
 payload={'engine':engine,'initialization_ms':initialization,'cpu_ms':(time.process_time()-cpu_start)*1000,'total_cpu_ms':(time.process_time()-cpu0)*1000,'peak_rss_mb':peak/2**20,'added_rss_mb':(peak-baseline)/2**20,'frame_p95_ms':float(np.percentile(ticks,95)),'audio_seconds':sum(x['duration'] for x in out),'cases':out}
 (ROOT/(engine+'-results.json')).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
 print(json.dumps({k:v for k,v in payload.items() if k!='cases'}));print([(x['name'],x['endpoint_delay_ms'],x['cut'],x['missed'],x['false_turns']) for x in out])

def smart_profile():
 import asyncio, shutil
 from core.smart_turn import SmartTurn, SHA256, FILENAME
 model=SmartTurn(ROOT/'smart-runtime');model.path.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(ROOT/FILENAME,model.path);model.path.with_suffix('.sha256').write_text(SHA256)
 async def profile():
  start=time.perf_counter()
  try:
   if not await model.warm():raise RuntimeError('Smart Turn unavailable')
   warm=(time.perf_counter()-start)*1000;worker=psutil.Process(model.process.pid)
   def usage():
    family=[worker,*worker.children(recursive=True)];cpu=0;rss=0;private=0
    for child in family:
     t=child.cpu_times();m=child.memory_info();cpu+=t.user+t.system;rss+=m.rss;private+=getattr(m,'private',m.rss)
    return cpu,rss,private
   before,peak,private=usage();results=[]
   for case in json.loads((ROOT/'corpus.json').read_text()):
    for _,end in case['speech']:
     audio=read(case['path'])[:int((end+.5)*16000)][-128000:]
     import io
     output=io.BytesIO()
     with wave.open(output,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes((audio*32767).astype('<i2').tobytes())
     result=await model.evaluate(output.getvalue());cpu,rss,private_now=usage();peak=max(peak,rss);private=max(private,private_now);results.append({'case':case['name'],**result})
   cpu,_,_=usage();report={'warm_ms':warm,'cpu_ms':(cpu-before)*1000,'worker_family_rss_mb':peak/2**20,'worker_family_private_mb':private/2**20,'cases':results}
   (ROOT/'smart-resource.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
  finally:await model.close()
 asyncio.run(profile())

if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Synthetic, offline VAD comparison; never opens a microphone or changes application settings.');parser.add_argument('--engine',choices=['ten','silero','webrtc']);parser.add_argument('--prepare',action='store_true');parser.add_argument('--smart-profile',action='store_true');args=parser.parse_args()
 if args.prepare:prepare()
 elif args.smart_profile:smart_profile()
 elif args.engine:run(args.engine)
 else:corpus()
