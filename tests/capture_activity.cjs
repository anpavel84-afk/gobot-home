// Capture lifecycle/silence fixtures. No real browser or cloud calls.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let now=0,amplitude=128,stopped=0,submitted=0,errors=0,serial=0;const meters=new Map();
const track={stop(){stopped++;},addEventListener(){}};
class Recorder{
  static isTypeSupported(){return true;}constructor(){this.state='inactive';}start(){this.state='recording';}
  stop(){if(this.state!=='recording')return;this.state='inactive';this.ondataavailable({data:new Blob(['fixture'])});this.onstop();}
}
const context={window:{isSecureContext:true},navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[track],getAudioTracks:()=>[track]})}},
  performance:{now:()=>now},MediaRecorder:Recorder,Blob,DOMException,Error,Uint8Array,
  setTimeout:()=>++serial,clearTimeout(){},setInterval:cb=>{meters.set(++serial,cb);return serial;},clearInterval:id=>meters.delete(id)};
vm.createContext(context);vm.runInContext(fs.readFileSync('services/phone/dist/capture.js','utf8'),context);
const capture=context.window.GoBotCapture,audio={createAnalyser:()=>({fftSize:512,getByteTimeDomainData:data=>data.fill(amplitude)}),createMediaStreamSource:()=>({connect(){},disconnect(){}})};
const options=()=>({context:audio,minDurationMs:400,minSpeechMs:180,onStop:()=>submitted++,onError:()=>errors++});
(async()=>{
  let handle=await capture.start(options());now=1000;for(const cb of meters.values())cb();handle.stop();assert.equal(submitted,0);assert.equal(errors,1);assert(!capture.active&&meters.size===0);
  amplitude=160;handle=await capture.start(options());for(let i=0;i<5;i++){now+=100;for(const cb of meters.values())cb();}handle.stop();handle.stop();assert.equal(submitted,1);assert(!capture.active);
  const abort=new AbortController();handle=await capture.start({...options(),signal:abort.signal});abort.abort();handle.cancel();assert.equal(submitted,1);assert(!capture.active&&meters.size===0);
  const next=await capture.start(options());handle.cancel();assert(capture.active===next);next.cancel();
  const already=new AbortController();already.abort();await assert.rejects(capture.start({...options(),signal:already.signal}),/отменена/);assert(!capture.pending);
  console.log('Capture units: silence/short-touch gating, one final, abort, repeated cleanup and track release passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
