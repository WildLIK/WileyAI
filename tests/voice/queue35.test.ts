import test from "node:test";
import assert from "node:assert/strict";
import { Conversation } from "../../src/voice/conversation.ts";

const tick = () => new Promise((resolve) => setTimeout(resolve, 10));
class Capture {
  sampleRate=16000; receive: ((frame: Float32Array)=>void) | null=null;
  async start(receive: (frame: Float32Array)=>void) { this.receive=receive; }
  async stop() { this.receive=null; }
  phrase(value=.1) { for(let i=0;i<25;i++) this.receive?.(new Float32Array(320).fill(value)); for(let i=0;i<55;i++) this.receive?.(new Float32Array(320)); }
}
for(const mode of ["sequential","latest","queue"] as const) test(`explicit ${mode} pending policy is bounded and stop removes late work`, async()=>{
  const capture=new Capture(); let release=()=>{}, calls=0, turns=0;
  const session=new Conversation({capture,queueMode:mode,listenWhileThinking:true,cooldownMs:0,prepare:async()=>{},onPhase:()=>{},onError:(e)=>{throw e;},
    transcribe:async()=>`Фраза ${++calls}`,
    onTurn:async(_audio,signal,phase)=>{turns++;phase("thinking"); if(turns===1) await new Promise<void>(resolve=>{release=resolve;signal.addEventListener("abort",()=>resolve(),{once:true});});},
  });
  try{
    await session.start();capture.phrase();await tick();
    for(let i=0;i<4;i++)capture.phrase();await tick();
    assert.equal(calls,mode==="sequential"||mode==="latest"?1:4);
    release();await tick();await tick();
    assert.equal(turns,mode==="sequential"?1:mode==="latest"?2:4);
    await session.stop();capture.phrase();await tick();assert.equal(session.phase,"idle");
  }finally{await session.stop();}
});
test("latest duplicate and expired queued samples cannot execute after a slow request",async()=>{
  for(const expire of [false,true]){
    const capture=new Capture();let release=()=>{},turns=0;
    const session=new Conversation({capture,queueMode:"latest",pendingMaxAgeMs:expire?1:15000,listenWhileThinking:true,cooldownMs:0,prepare:async()=>{},onPhase:()=>{},onError:(e)=>{throw e;},transcribe:async()=>"Повтор",
      onTurn:async()=>{turns++;await new Promise<void>(resolve=>{release=resolve;});},
    });
    try{await session.start();capture.phrase();await tick();capture.phrase();await tick();release();await tick();await tick();assert.equal(turns,1);assert.ok(session.events.some(e=>e.name==="request_cancelled"&&e.reason===(expire?"queued_expired":"duplicate_queued")));}finally{await session.stop();}
  }
});
