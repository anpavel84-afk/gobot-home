// Execute the real browser functions, not a replacement play callback.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('services/phone/dist/browser.js','utf8');
const nodes={speak:{checked:true},paid:{checked:true},volume:{value:'.8'},tts:{value:'openai'},voice:{value:'marin'}};
let started=[],now=3000;const jobs=[];
const audio={state:'running',currentTime:0,decodeAudioData:async()=>buffer,createBuffer(n,length,rate){const pcm=new Float32Array(length);return {duration:length/rate,getChannelData:()=>pcm};},createBufferSource(){return {connect(){},stop(at){this.stoppedAt=at;},start(at){this.startedAt=at;started.push(this);}};}};
const buffer={duration:2};
const env={window:{},document:{hidden:false},Map,Set,AbortController,Uint8Array,DataView,atob,performance:{now:()=>now},setTimeout:(f)=>{jobs.push(f);return jobs.length;},clearTimeout(){},fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(100)}),openingFetchAbort:null,openingDecoded:new Map(),
 audio,feedbackGain:{gain:{value:.2,cancelScheduledValues(){},setValueAtTime(){},linearRampToValueAtTime(){}}},earconBuffer:{duration:.08},feedbackSources:new Set(),$:id=>nodes[id],epoch:1,requestTrace:null};
vm.createContext(env);vm.runInContext(fs.readFileSync('services/phone/dist/turn-trace.js','utf8'),env);
vm.runInContext(source.slice(source.indexOf('function stopFeedback('),source.indexOf('function inputClosed(')),env);
Object.assign(env,{seen:new Set(),audioSequences:new Map(),sources:new Set(),playedSegments:new Map(),nextAt:0,currentTurn:'fixture-turn',gain:{}});
vm.runInContext(source.slice(source.indexOf('async function play('),source.indexOf('function stop(preserveWaiting')),env);
const {TurnTrace}=env.window.GoBotTiming;
(async()=>{
 const trace=new TurnTrace('actual-client').inputClosed(0);env.requestTrace=trace;
 vm.runInContext('feedback.begin(requestTrace)',env);jobs.shift()();
 const opening={id:'opening-001',voice:'marin',url:'/api/speech/openings/marin/opening-001.wav'};env.opening=opening;
 await vm.runInContext('offerOpening(opening,requestTrace,epoch)',env);
 const fillers=started.filter(x=>x.gobotAudioRole==='filler');assert.equal(fillers.length,1);assert.equal(fillers[0].buffer,buffer);
 assert(trace.events.some(e=>e.name==='filler_started'));
 const pcm=Buffer.alloc(480);pcm.writeInt16LE(2000,0);env.packet={audio_id:'real-answer',seq:0,format:'pcm_s16le',sample_rate:24000,pcm:pcm.toString('base64')};
 await vm.runInContext('play(packet,epoch)',env);
 const answer=started.find(x=>x.gobotAudioRole==='answer');assert(answer);assert(fillers[0].stoppedAt<=answer.startedAt,'main answer must follow filler fade, no overlap');
 // Actual functions recheck voice, mute and epoch immediately before start.
 for(const scenario of ['voice','mute','cancel','hidden','decode-error','http-error','web-audio-error']){
   started=[];env.epoch++;now+=4000;const t=new TurnTrace(scenario).inputClosed(now-3000);env.requestTrace=t;
   vm.runInContext('feedback.begin(requestTrace)',env);jobs.pop()();
   const original=env.fetch,decode=audio.decodeAudioData,create=audio.createBufferSource;
   env.openingDecoded.clear();
   if(scenario==='decode-error')audio.decodeAudioData=async()=>{throw Error('broken');};
   if(scenario==='http-error')env.fetch=async()=>({ok:false});
   if(scenario==='web-audio-error')audio.createBufferSource=()=>{throw Error('closed');};
   if(['voice','mute','cancel','hidden'].includes(scenario))audio.decodeAudioData=async()=>{
     if(scenario==='voice')nodes.voice.value='cedar';
     if(scenario==='mute')nodes.speak.checked=false;
     if(scenario==='cancel')vm.runInContext('feedback.cancel()',env);
     if(scenario==='hidden')env.document.hidden=true;
     return buffer;
   };
   await vm.runInContext('offerOpening(opening,requestTrace,epoch)',env);
   assert.equal(started.filter(s=>s.gobotAudioRole==='filler').length,0,scenario);
   nodes.voice.value='marin';nodes.speak.checked=true;env.document.hidden=false;env.fetch=original;audio.decodeAudioData=decode;audio.createBufferSource=create;
 }
 console.log('Real browser offer/fetch/decode/controller/playFeedback/AudioBufferSource.start passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
